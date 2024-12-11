from flask import Flask, redirect, request, session, render_template
import requests
import os
import subprocess
from dotenv import load_dotenv
from models import SessionLocal, User, Giveaway, Item, Winner
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
import psutil

# Load environment variables
load_dotenv()

# Flask application setup
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Twitch API credentials
CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:5000/auth/twitch/callback"

chatbot_processes = {}

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/auth/twitch")
def auth_twitch():
    return redirect(
        f"https://id.twitch.tv/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=user:read:email"
    )

@app.route("/auth/twitch/callback")
def auth_twitch_callback():
    """Handle Twitch OAuth callback."""
    code = request.args.get("code")
    if not code:
        return "Authorization failed: missing code", 400

    try:
        # Exchange the authorization code for an access token
        token_response = requests.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
            },
        )
        token_response.raise_for_status()  # Raise an error for HTTP errors
        token_data = token_response.json()

        # Check for access_token in the response
        if "access_token" not in token_data:
            app.logger.error("Twitch API response missing access_token.")
            return "Authorization failed: missing access token", 400

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Twitch API error during token exchange: {e}")
        return "Authorization failed due to Twitch API error", 400

    try:
        # Use the access token to fetch user data
        user_response = requests.get(
            "https://api.twitch.tv/helix/users",
            headers={
                "Authorization": f"Bearer {token_data['access_token']}",
                "Client-Id": CLIENT_ID
            }
        )
        user_response.raise_for_status()
        user_data = user_response.json()


        # Ensure user data contains the required fields
        if "data" not in user_data or not user_data["data"]:
            app.logger.error("Twitch user data is missing or empty.")
            return "Authorization failed: unable to fetch user data", 400

        user_info = user_data["data"][0]  # Extract the first user in the data list

        # Log the user in or create a new user in the database
        db_session = SessionLocal()
        user = db_session.query(User).filter_by(twitch_id=user_info["id"]).first()
        if not user:
            # Create a new user
            user = User(
                twitch_id=user_info["id"],
                username=user_info["display_name"],
            )
            db_session.add(user)
            db_session.commit()

        # Store the user ID in the session
        session["user_id"] = user.id
        session["username"] = user_info["display_name"]  # Add this line to store the username
        db_session.close()

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Twitch API error while fetching user data: {e}")
        return "Authorization failed due to Twitch API error", 400
    except Exception as e:
        app.logger.error(f"Unexpected error: {e}")
        return "Authorization failed due to an unexpected error", 400

    return redirect("/dashboard")

@app.route("/dashboard")
def dashboard():
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/auth/twitch")
    
    db_session = SessionLocal()
    giveaways = db_session.query(Giveaway).filter_by(creator_id=user_id).all()
    winners = db_session.query(Winner).join(Giveaway).filter(Giveaway.creator_id == user_id).all()
    db_session.close()

    return render_template("dashboard.html", giveaways=giveaways, winners=winners)

@app.route("/giveaway/create", methods=["GET", "POST"])
def create_giveaway():
    user_id = session.get("user_id")  # Get the logged-in user's ID
    if not user_id:
        return redirect("/auth/twitch")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        frequency = request.form.get("frequency", "").strip()
        threshold = request.form.get("threshold", "").strip()

        # Input validation
        try:
            if not title:
                raise ValueError("Title is required.")
            if not frequency.isdigit() or not threshold.isdigit():
                raise ValueError("Frequency and threshold must be valid numbers.")
            frequency = int(frequency)
            threshold = int(threshold)
            if frequency <= 0 or threshold < 0 or frequency > 1_000_000:
                raise ValueError("Frequency or threshold out of valid range.")
        except ValueError as e:
            return f"Invalid input: {str(e)}", 400

        # Add sanitization to prevent SQL injection
        if ";" in title or "--" in title or "'" in title:
            return {"error": "Invalid input detected. Special characters are not allowed."}, 400
        
        if len(title) > 255:
            return {"error": "Title exceeds the maximum length of 255 characters."}, 400

        db_session = SessionLocal()
        user = db_session.query(User).filter_by(id=user_id).first()
        if not user:
            db_session.close()
            return "User not found.", 403

        # Create a new Giveaway object
        giveaway = Giveaway(
            title=title,
            frequency=frequency,
            threshold=threshold,
            creator_id=user.id
        )
        db_session.add(giveaway)
        db_session.commit()
        db_session.close()

        return redirect("/dashboard")

    return render_template("create_giveaway.html")

@app.route("/giveaways")
def list_giveaways():
    user_id = session.get("user_id")
    db_session = SessionLocal()
    giveaways = db_session.query(Giveaway).filter_by(creator_id=user_id).all()
    db_session.close()

    return "<br>".join([f"ID: {g.id}, Title: {g.title}" for g in giveaways])

@app.route("/giveaway/delete/<int:id>", methods=["POST", "GET"])
def delete_giveaway(id):
    """
    Deletes a giveaway while retaining won items in the database.
    Retained won items will keep their `giveaway_id`.
    """
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/auth/twitch")

    db_session = SessionLocal()
    giveaway = db_session.query(Giveaway).filter_by(id=id, creator_id=user_id).first()

    if not giveaway:
        db_session.close()
        return "Giveaway not found or you do not have permission to delete it.", 403

    # Process non-won items: Delete them
    non_won_items = db_session.query(Item).filter_by(giveaway_id=id, is_won=False).all()
    for item in non_won_items:
        db_session.delete(item)

    # Log won items (but do not delete them or modify `giveaway_id`)
    won_items = db_session.query(Item).filter_by(giveaway_id=id, is_won=True).all()
    for won_item in won_items:
        print(f"Retained won item: {won_item.name} (ID: {won_item.id})")

    # Finally, delete the giveaway
    db_session.delete(giveaway)

    try:
        db_session.commit()
    except IntegrityError as e:
        db_session.rollback()
        print(f"Error during giveaway deletion: {str(e)}")
        return "Failed to delete giveaway due to database constraints.", 500
    finally:
        db_session.close()

    return redirect("/dashboard")

@app.route("/giveaway/start/<int:giveaway_id>")
def start_giveaway(giveaway_id):
    """Start the giveaway and launch the chatbot."""
    lock_file = "chatbot.lock"

    # Check if the chatbot is already running
    if os.path.exists(lock_file):
        with open(lock_file, "r") as f:
            pid = int(f.read().strip())
        if psutil.pid_exists(pid):
            return "A chatbot is already running. Please wait for it to finish.", 400
        else:
            print(f"Stale lock file found with PID: {pid}. Removing it.")
            os.remove(lock_file)  # Clean up stale lock file


    db_session = SessionLocal()
    giveaway = db_session.query(Giveaway).filter_by(id=giveaway_id).first()
    db_session.close()

    if not giveaway:
        return "Giveaway not found.", 404

    # Start chatbot with the giveaway ID
    try:
        process = subprocess.Popen(["python", "chatbot.py", str(giveaway_id)])
        chatbot_processes[giveaway_id] = process  # Track the process
        with open(lock_file, "w") as f:
            f.write(str(process.pid))
        return redirect("/dashboard")
    except Exception as e:
        return f"Failed to start chatbot: {str(e)}", 500

@app.route("/giveaway/edit/<int:id>", methods=["GET", "POST"])
def edit_giveaway(id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/auth/twitch")

    db_session = SessionLocal()
    giveaway = db_session.query(Giveaway).options(joinedload(Giveaway.items)).filter_by(id=id).first()
    if not giveaway:
        db_session.close()
        return "Giveaway not found.", 404

    if giveaway.creator_id != user_id:
        db_session.close()
        return "Unauthorized to edit this giveaway.", 403

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        frequency = request.form.get("frequency", "").strip()
        threshold = request.form.get("threshold", "").strip()
        if not title or not frequency.isdigit() or not threshold.isdigit():
            db_session.close()
            return "Invalid input. Ensure all fields are filled correctly.", 400
        giveaway.title = title
        giveaway.frequency = int(frequency)
        giveaway.threshold = int(threshold)
        db_session.commit()
        db_session.close()
        return redirect("/dashboard")

    db_session.close()
    return render_template("edit_giveaway.html", giveaway=giveaway)

@app.route("/giveaway/view/<int:giveaway_id>", methods=["GET"])
def view_giveaway(giveaway_id):
    """
    View a giveaway and handle active or expired states.
    """
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/auth/twitch")

    db_session = SessionLocal()
    giveaway = db_session.query(Giveaway).filter_by(id=giveaway_id).first()

    if not giveaway:
        db_session.close()
        return "Giveaway not found.", 404

    if not giveaway.active:
        db_session.close()
        return "This giveaway is no longer active.", 400

    db_session.close()
    return render_template("view_giveaway.html", giveaway=giveaway)

@app.route("/giveaway/add-item/<int:giveaway_id>", methods=["POST"])
def add_item(giveaway_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/auth/twitch")

    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip()

    # Improved validation for specific error messages
    if not name:
        return "Item name is required.", 400
    if not code:
        return "Item code is required.", 400

    db_session = SessionLocal()
    giveaway = db_session.query(Giveaway).filter_by(id=giveaway_id).first()
    if not giveaway:
        db_session.close()
        return "Giveaway not found.", 404

    item = Item(name=name, code=code, giveaway_id=giveaway_id)
    db_session.add(item)
    db_session.commit()
    db_session.close()

    return redirect(f"/giveaway/edit/{giveaway_id}")

# Update: Enhancing the remove-item route to support AJAX requests.
@app.route("/giveaway/remove-item/<int:item_id>", methods=["POST"])
def remove_item(item_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/auth/twitch")

    db_session = SessionLocal()
    try:
        # Query for the item and ensure it belongs to a giveaway created by the logged-in user
        item = db_session.query(Item).join(Giveaway, Giveaway.id == Item.giveaway_id).filter(
            Item.id == item_id,
            Giveaway.creator_id == user_id
        ).first()

        print(f"Queried item: {item}")


        if not item:
            return "Item not found or permission denied.", 403

        # Capture giveaway ID before deletion
        giveaway_id = item.giveaway_id
        db_session.delete(item)
        db_session.commit()

        return redirect(f"/giveaway/edit/{giveaway_id}")
    except Exception as e:
        print(f"Error removing item: {e}")
        return "An error occurred while trying to remove the item.", 500
    finally:
        db_session.close()


@app.route("/giveaway/stop/<int:giveaway_id>")
def stop_giveaway(giveaway_id):
    """Stop the giveaway and terminate the chatbot."""
    lock_file = "chatbot.lock"

    # Check for a running chatbot process
    if giveaway_id in chatbot_processes:
        process = chatbot_processes.pop(giveaway_id)
        process.terminate()
        process.wait()  # Wait for the process to terminate
        print(f"Terminated chatbot process for giveaway {giveaway_id}")

    # Remove lock file if it exists
    if os.path.exists(lock_file):
        os.remove(lock_file)
        print("Lock file removed successfully.")
    else:
        print("No lock file found.")

    return "No running chatbot found for this giveaway.", 404


@app.route("/winnings")
def winnings():
    user_username = session.get("username")
    if not user_username:
        return redirect("/auth/twitch")  # Redirect only if the username is not set

    db_session = SessionLocal()
    winnings = (
        db_session.query(Item)
        .filter(Item.is_won == True, Item.winner_username == user_username)
        .all()
    )
    db_session.close()

    return render_template("winnings.html", winnings=winnings)

if __name__ == "__main__":
    app.run(debug=True)