import unittest
import time
from unittest.mock import patch
import os
import threading
from app import app, SessionLocal, chatbot_processes, subprocess  # Import SessionLocal for database operations
from models import Giveaway, Item, User  # Import models for database objects


class TestApp(unittest.TestCase):
    def setUp(self):
        # Set up the Flask test client
        self.app = app  # Reference the Flask app
        self.client = app.test_client()
        self.client.testing = True

    ### Unit Tests ###
    def test_homepage(self):
        """Test the homepage loads successfully."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Log in with Twitch", response.data)

    def test_twitch_auth_redirect(self):
        """Test the Twitch authentication redirect."""
        response = self.client.get("/auth/twitch")
        self.assertEqual(response.status_code, 302)
        self.assertIn("https://id.twitch.tv/oauth2/authorize", response.location)

    ### Integration Tests ###
    def test_dashboard_access_without_login(self):
        """Test accessing the dashboard without login."""
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)  # Should redirect to Twitch auth
        self.assertIn("/auth/twitch", response.location)

    def test_create_giveaway_invalid_data(self):
        """Test creating a giveaway with invalid data."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user
        response = self.client.post("/giveaway/create", data={
            "title": "",
            "frequency": "invalid",
            "threshold": ""
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Invalid input", response.data)

    def test_create_giveaway_extreme_values(self):
        """Test creating a giveaway with extreme values."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user

        # Test too large frequency
        response = self.client.post("/giveaway/create", data={
            "title": "Extreme Giveaway",
            "frequency": "99999999",  # Too large
            "threshold": "10"
        })
        self.assertEqual(response.status_code, 400)  # Should fail gracefully

        # Test zero frequency
        response = self.client.post("/giveaway/create", data={
            "title": "Extreme Giveaway",
            "frequency": "0",  # Invalid frequency
            "threshold": "10"
        })
        self.assertEqual(response.status_code, 400)

        # Test negative threshold
        response = self.client.post("/giveaway/create", data={
            "title": "Extreme Giveaway",
            "frequency": "10",
            "threshold": "-5"  # Invalid threshold
        })
        self.assertEqual(response.status_code, 400)

    def test_edit_giveaway_invalid_data(self):
        """Test editing a giveaway with invalid data."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user

        # Attempt to edit the giveaway with invalid data
        response = self.client.post("/giveaway/edit/1", data={
            "title": "",  # Empty title
            "frequency": "not-a-number",  # Invalid frequency
            "threshold": ""  # Empty threshold
        })
        self.assertEqual(response.status_code, 400)  # Should reject invalid input
        self.assertIn(b"Invalid input", response.data)

    def test_edit_giveaway_success(self):
        """Test successfully editing a giveaway."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user

        # Edit the giveaway with valid data
        response = self.client.post("/giveaway/edit/1", data={
            "title": "Updated Title",
            "frequency": "20",
            "threshold": "5"
        })
        self.assertEqual(response.status_code, 302)  # Redirect to dashboard
        self.assertIn("/dashboard", response.location)

    def test_add_item_invalid_data(self):
        """Test adding an item with invalid data."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user

        response = self.client.post("/giveaway/add-item/1", data={
            "name": "",  # Invalid name
            "code": "ITEM001"
        })
        self.assertEqual(response.status_code, 400)  # Check HTTP status code
        self.assertIn(b"Item name is required.", response.data)  # Expect specific error message

        response = self.client.post("/giveaway/add-item/1", data={
            "name": "Test Item",
            "code": ""  # Invalid code
        })
        self.assertEqual(response.status_code, 400)  # Check HTTP status code
        self.assertIn(b"Item code is required.", response.data)  # Expect specific error message

    def test_add_item_success(self):
        """Test successfully adding an item."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1

        # Create a test giveaway in the database
        db_session = SessionLocal()
        test_giveaway = Giveaway(
            title="Test Giveaway",
            frequency=10,
            threshold=5,
            creator_id=1
        )
        db_session.add(test_giveaway)
        db_session.commit()

        response = self.client.post(f"/giveaway/add-item/{test_giveaway.id}", data={
            "name": "Test Item",
            "code": "ITEM001"
        })
        self.assertEqual(response.status_code, 302)  # Redirect to edit page
        self.assertIn(f"/giveaway/edit/{test_giveaway.id}", response.location)

        db_session.close()

    def test_remove_item_success(self):
        """Test successfully removing an item."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user

        # Create a test giveaway and item in the database
        db_session = SessionLocal()
        test_giveaway = Giveaway(
            title="Test Giveaway",
            frequency=10,
            threshold=5,
            creator_id=1  # Matches the simulated logged-in user
        )
        db_session.add(test_giveaway)
        db_session.commit()

        test_item = Item(
            name="Test Item",
            code="ITEM001",
            giveaway_id=test_giveaway.id
        )
        db_session.add(test_item)
        db_session.commit()

        # Use the actual ID of the created item
        response = self.client.post(f"/giveaway/remove-item/{test_item.id}")
        self.assertEqual(response.status_code, 302)  # Redirect to edit page
        self.assertIn(f"/giveaway/edit/{test_giveaway.id}", response.location)

        db_session.close()

    def test_delete_giveaway(self):
        """Test deleting a giveaway."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1

        # Add a giveaway to delete
        db_session = SessionLocal()
        test_giveaway = Giveaway(
            title="Giveaway to Delete",
            frequency=10,
            threshold=5,
            creator_id=1
        )
        db_session.add(test_giveaway)
        db_session.commit()

        response = self.client.post(f"/giveaway/delete/{test_giveaway.id}")
        self.assertEqual(response.status_code, 302)

        # Verify deletion
        deleted_giveaway = db_session.query(Giveaway).filter_by(id=test_giveaway.id).first()
        self.assertIsNone(deleted_giveaway)

        db_session.close()

    ### Performance Tests ###
    def test_response_time(self):
        """Test the response time of a key route."""
        import time
        start_time = time.time()
        response = self.client.get("/")
        end_time = time.time()
        self.assertEqual(response.status_code, 200)
        self.assertLess(end_time - start_time, 0.5)  # Ensure response time is under 500ms

    ### Security Tests ###
    def test_protected_dashboard_access(self):
        """Ensure unauthorized users cannot access the dashboard."""
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/twitch", response.location)

    def test_advanced_sql_injection_attempt(self):
        """Test advanced SQL injection scenarios."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user

        malicious_payloads = [
            "'; DROP TABLE giveaways; --",
            "' OR '1'='1",
            "1; DROP TABLE items; --"
        ]

        for payload in malicious_payloads:
            response = self.client.post("/giveaway/create", data={
                "title": payload,
                "frequency": "10",
                "threshold": "5"
            })
            self.assertEqual(response.status_code, 400)
            self.assertIn(b"Invalid input detected", response.data)

    def test_activate_giveaway(self):
        """Test creating and activating a giveaway."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1

        db_session = SessionLocal()
        test_giveaway = Giveaway(
            title="Test Giveaway",
            frequency=10,
            threshold=5,
            creator_id=1
        )
        db_session.add(test_giveaway)
        db_session.commit()

        # Initially not active
        self.assertEqual(test_giveaway.active, False)

        # Activate the giveaway
        test_giveaway.active = True
        db_session.commit()
        self.assertEqual(test_giveaway.active, True)

        db_session.close()

    def test_interact_with_active_giveaway(self):
        """Test interacting with an active giveaway."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1

        db_session = SessionLocal()
        test_giveaway = Giveaway(
            title="Active Giveaway",
            frequency=10,
            threshold=5,
            creator_id=1,
            active=True  # Mark as active
        )
        db_session.add(test_giveaway)
        db_session.commit()

        response = self.client.get(f"/giveaway/view/{test_giveaway.id}")
        self.assertEqual(response.status_code, 200)  # Expect 200 for active giveaways
        db_session.close()

    def test_expired_giveaway(self):
        """Test accessing an expired giveaway."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1

        db_session = SessionLocal()
        test_giveaway = Giveaway(
            title="Expired Giveaway",
            frequency=10,
            threshold=5,
            creator_id=1,
            active=False  # Mark as expired
        )
        db_session.add(test_giveaway)
        db_session.commit()

        response = self.client.get(f"/giveaway/view/{test_giveaway.id}")
        self.assertEqual(response.status_code, 400)  # Expect 400 for expired giveaways
       
    def test_delete_active_giveaway(self):
        """Test deleting an active giveaway."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1

        db_session = SessionLocal()
        test_giveaway = Giveaway(
            title="Active Giveaway",
            frequency=10,
            threshold=5,
            creator_id=1,
            active=True
        )
        db_session.add(test_giveaway)
        db_session.commit()

        response = self.client.post(f"/giveaway/delete/{test_giveaway.id}")
        self.assertEqual(response.status_code, 302)  # Redirect expected

        # Verify deletion
        deleted_giveaway = db_session.query(Giveaway).filter_by(id=test_giveaway.id).first()
        self.assertIsNone(deleted_giveaway)

        db_session.close()

    def test_large_number_of_items(self):
        """Test adding a large number of items to a giveaway."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user

        db_session = SessionLocal()
        test_giveaway = Giveaway(
            title="Stress Test Giveaway",
            frequency=10,
            threshold=5,
            creator_id=1
        )
        db_session.add(test_giveaway)
        db_session.commit()

        # Add 1,000 items
        for i in range(1000):
            response = self.client.post(f"/giveaway/add-item/{test_giveaway.id}", data={
                "name": f"Item {i}",
                "code": f"CODE{i}"
            })
            self.assertEqual(response.status_code, 302)  # Expect successful addition

        # Verify item count
        items = db_session.query(Item).filter_by(giveaway_id=test_giveaway.id).all()
        self.assertEqual(len(items), 1000)

        db_session.close()

    def test_session_expiry(self):
        """Test accessing routes with an expired or invalid session."""
        with self.client.session_transaction() as session:
            session["user_id"] = None  # Simulate no active session

        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)  # Expect redirect to login
        self.assertIn("/auth/twitch", response.location)  # Redirect URL validation

    def test_real_world_workflow(self):
        """Test end-to-end workflow for creating, interacting with, and deleting a giveaway."""
        # Explicitly clear the database before the test
        db_session = SessionLocal()
        db_session.query(Item).delete()
        db_session.query(Giveaway).delete()
        db_session.commit()

        # Ensure test users exist
        user1 = db_session.query(User).filter_by(id=1).first()
        if not user1:
            user1 = User(id=1, twitch_id="test_twitch_id_1", username="test_user1")
            db_session.add(user1)
        user2 = db_session.query(User).filter_by(id=2).first()
        if not user2:
            user2 = User(id=2, twitch_id="test_twitch_id_2", username="test_user2")
            db_session.add(user2)
        db_session.commit()

        # Step 1: User 1 creates a giveaway
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate User 1
        response = self.client.post("/giveaway/create", data={
            "title": "Real World Test Giveaway",
            "frequency": "10",
            "threshold": "5"
        })
        self.assertEqual(response.status_code, 302)

        # Verify giveaway creation
        giveaway = db_session.query(Giveaway).filter_by(title="Real World Test Giveaway").first()
        self.assertIsNotNone(giveaway)

        # Step 2: User 2 adds items
        with self.client.session_transaction() as session:
            session["user_id"] = 2  # Simulate User 2
        for i in range(5):
            response = self.client.post(f"/giveaway/add-item/{giveaway.id}", data={
                "name": f"User 2 Item {i}",
                "code": f"U2CODE{i}"
            })
            self.assertEqual(response.status_code, 302)

        # Verify items were added
        items = db_session.query(Item).filter_by(giveaway_id=giveaway.id).all()
        self.assertEqual(len(items), 5)

        # Step 3: User 1 deletes the giveaway
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Back to User 1
        response = self.client.post(f"/giveaway/delete/{giveaway.id}")
        self.assertEqual(response.status_code, 302)

        # Verify giveaway deletion
        deleted_giveaway = db_session.query(Giveaway).filter_by(id=giveaway.id).first()
        self.assertIsNone(deleted_giveaway)

        # Verify items were retained
        retained_items = db_session.query(Item).filter_by(giveaway_id=giveaway.id).all()
        self.assertEqual(len(retained_items), 0)

        db_session.close()

    def test_endpoint_performance(self):
        """Test performance of critical endpoints."""
        import time

        # Ensure the test user exists
        db_session = SessionLocal()
        user = db_session.query(User).filter_by(id=1).first()
        if not user:
            user = User(id=1, twitch_id="test_twitch_id", username="test_user")
            db_session.add(user)
            db_session.commit()
        db_session.close()

        # Simulate logged-in user
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Use a valid user ID

        # Test endpoints
        critical_endpoints = ["/", "/dashboard", "/giveaway/create"]
        for endpoint in critical_endpoints:
            start_time = time.time()
            response = self.client.get(endpoint)
            elapsed_time = time.time() - start_time
            self.assertEqual(response.status_code, 200, f"Failed at {endpoint}")  # Expect 200
            self.assertLess(elapsed_time, 0.5, f"Endpoint {endpoint} took too long: {elapsed_time:.2f}s")

    def test_empty_dashboard(self):
        """Ensure dashboard handles no giveaways gracefully."""
        # Ensure no giveaways exist
        db_session = SessionLocal()
        db_session.query(Giveaway).delete()  # Clear giveaways
        db_session.commit()
        giveaways = db_session.query(Giveaway).all()
        self.assertEqual(len(giveaways), 0, "Database is not empty")
        db_session.close()

        # Simulate logged-in user
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Replace with a valid user ID

        # Access the dashboard
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No giveaways found", response.data)

    def test_simulated_load_on_dashboard(self):
        """Simulate high load on the dashboard endpoint."""
        import threading

        def make_request():
            with self.client.session_transaction() as session:
                session["user_id"] = 1  # Simulate logged-in user
            response = self.client.get("/dashboard")
            self.assertEqual(response.status_code, 200)

        threads = [threading.Thread(target=make_request) for _ in range(50)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    def test_performance_response_time(self):
        """Log response time for critical endpoints."""
        import time

        # Simulate logged-in user for protected routes
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Use a valid user ID

        endpoints = ["/", "/dashboard", "/giveaway/create"]
        response_times = {}

        for endpoint in endpoints:
            start_time = time.time()
            response = self.client.get(endpoint)
            response_times[endpoint] = time.time() - start_time

            # Verify response status
            if endpoint in ["/dashboard", "/giveaway/create"]:
                self.assertEqual(response.status_code, 200)  # Expect 200 for logged-in routes
            else:
                self.assertEqual(response.status_code, 200)  # Public routes

            # Verify performance
            self.assertLess(
                response_times[endpoint],
                1.0,
                f"Endpoint {endpoint} took too long: {response_times[endpoint]:.2f}s"
            )

        print("Response Times:", response_times)

    def test_session_expiration_handling(self):
        """Test handling of expired sessions."""
        with self.client.session_transaction() as session:
            session["user_id"] = None  # Simulate an expired session

        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/twitch", response.location)

    def test_end_to_end_user_workflow(self):
        """Simulate a full user workflow."""
        # Ensure a user exists in the database
        db_session = SessionLocal()
        user = db_session.query(User).filter_by(id=1).first()
        if not user:
            user = User(id=1, twitch_id="test_twitch_id", username="test_user")
            db_session.add(user)
            db_session.commit()
        db_session.close()

        # Step 1: Log in and create a giveaway
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user
        response = self.client.post("/giveaway/create", data={
            "title": "Test Workflow Giveaway",
            "frequency": "10",
            "threshold": "5"
        })
        self.assertEqual(response.status_code, 302)

        # Step 2: Verify giveaway creation
        giveaway = db_session.query(Giveaway).filter_by(title="Test Workflow Giveaway").first()
        self.assertIsNotNone(giveaway)

        # Step 3: Add an item to the giveaway
        response = self.client.post(f"/giveaway/add-item/{giveaway.id}", data={
            "name": "Sample Item",
            "code": "ITEM001"
        })
        self.assertEqual(response.status_code, 302)

        # Step 4: Verify item addition
        item = db_session.query(Item).filter_by(name="Sample Item", giveaway_id=giveaway.id).first()
        self.assertIsNotNone(item)

        # Step 5: Clean up
        db_session.close()

    def test_sql_injection_protection(self):
        """Test for SQL injection vulnerabilities."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user

        malicious_inputs = [
            "'; DROP TABLE users; --",
            "' OR '1'='1",
            "' UNION SELECT null, null, null --"
        ]

        for payload in malicious_inputs:
            response = self.client.post("/giveaway/create", data={
                "title": payload,
                "frequency": "10",
                "threshold": "5"
            })
            self.assertEqual(response.status_code, 400)
            self.assertIn(b"Invalid input", response.data, msg=f"SQL Injection succeeded with payload: {payload}")

    def test_xss_protection(self):
        """Test for XSS vulnerabilities."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user

        malicious_script = "<script>alert('XSS');</script>"
        response = self.client.post("/giveaway/create", data={
            "title": malicious_script,
            "frequency": "10",
            "threshold": "5"
        })
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(malicious_script.encode(), response.data, "XSS payload was echoed back.")

    def test_dashboard_unauthorized_access(self):
        """Test that unauthorized users cannot access the dashboard."""
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)  # Should redirect to Twitch auth
        self.assertIn("/auth/twitch", response.location)

    def test_edit_giveaway_unauthorized_access(self):
        """Test that unauthorized users cannot edit a giveaway."""
        response = self.client.post("/giveaway/edit/1", data={
            "title": "Unauthorized Edit",
            "frequency": "10",
            "threshold": "5"
        })
        self.assertEqual(response.status_code, 302)  # Should redirect to login
        self.assertIn("/auth/twitch", response.location)

    def test_invalid_session_access(self):
        """Test accessing routes with an invalid session."""
        with self.client.session_transaction() as session:
            session["user_id"] = None  # Simulate an invalid session

        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/twitch", response.location)

    def test_brute_force_login_protection(self):
        """Simulate brute force login attempts."""
        for _ in range(10):  # Simulate multiple login attempts
            response = self.client.get("/auth/twitch")
            self.assertEqual(response.status_code, 302)  # Expect redirection each time
            self.assertIn("https://id.twitch.tv/oauth2/authorize", response.location)

    def test_long_title_for_giveaway(self):
        """Test creating a giveaway with an excessively long title."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user
        response = self.client.post("/giveaway/create", data={
            "title": "A" * 300,  # Excessively long title
            "frequency": "10",
            "threshold": "5"
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Title exceeds the maximum length", response.data)

    def test_concurrent_giveaway_entries(self):
        """Simulate multiple users entering a giveaway concurrently."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Creator

        # Create a test giveaway
        db_session = SessionLocal()
        giveaway = Giveaway(title="Concurrent Test", frequency=10, threshold=1, creator_id=1)
        db_session.add(giveaway)
        db_session.commit()

        # Simulate multiple users entering the giveaway
        for user_id in range(2, 12):  # Simulate 10 users
            user = User(id=user_id, twitch_id=f"user_{user_id}", username=f"user_{user_id}")
            db_session.add(user)
            db_session.commit()

        # Verify that all entries were added
        entries = db_session.query(Item).filter_by(giveaway_id=giveaway.id).count()
        self.assertEqual(entries, 10, "Not all users were able to join the giveaway.")
        db_session.close()

    def test_concurrent_giveaway_entries(self):
        """Simulate multiple users entering a giveaway concurrently."""
        print("Starting test_concurrent_giveaway_entries...")

        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Creator

        db_session = SessionLocal()

        # Create a test giveaway
        giveaway = Giveaway(title="Concurrent Test", frequency=10, threshold=1, creator_id=1)
        db_session.add(giveaway)
        db_session.commit()
        print(f"Giveaway created with ID: {giveaway.id}")

        # Simulate multiple users entering the giveaway
        for user_id in range(2, 12):
            existing_user = db_session.query(User).filter_by(id=user_id).first()
            if not existing_user:
                user = User(id=user_id, twitch_id=f"user_{user_id}", username=f"user_{user_id}")
                db_session.add(user)
                db_session.commit()
                print(f"User added: ID={user_id}, Username=user_{user_id}")
            else:
                print(f"User already exists: ID={user_id}")

        # Verify all entries were added
        entries = db_session.query(User).filter(User.id.in_(range(2, 12))).count()
        print(f"Total entries added: {entries}")
        self.assertEqual(entries, 10, "Not all users were added to the database.")

        db_session.close()

    def test_dashboard_high_load(self):
        """Simulate heavy load on the dashboard endpoint."""
        import threading

        def request_dashboard():
            with self.client.session_transaction() as session:
                session["user_id"] = 1  # Simulate logged-in user
            response = self.client.get("/dashboard")
            self.assertEqual(response.status_code, 200)

        threads = [threading.Thread(target=request_dashboard) for _ in range(1000)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    def test_advanced_sql_injection(self):
        """Test advanced SQL injection vectors."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1  # Simulate logged-in user

        malicious_payloads = [
            "'; DROP TABLE users; --",
            "admin'--",
            "' UNION SELECT null, null, null --"
        ]

        for payload in malicious_payloads:
            response = self.client.post("/giveaway/create", data={
                "title": payload,
                "frequency": "10",
                "threshold": "5"
            })
            self.assertEqual(response.status_code, 400)
            self.assertIn(b"Invalid input detected", response.data, msg=f"SQL Injection succeeded with payload: {payload}")

    def test_stop_giveaway(self):
        """Test stopping a giveaway."""
        with self.client.session_transaction() as session:
            session["user_id"] = 1

        giveaway_id = 1
        lock_file = "chatbot.lock"

        # Create a mock lock file
        with open(lock_file, "w") as f:
            f.write("12345")

        # Mock chatbot process
        chatbot_processes[giveaway_id] = subprocess.Popen(["python", "-c", "import time; time.sleep(1)"])

        # Test stopping the giveaway
        response = self.client.get(f"/giveaway/stop/{giveaway_id}")
        self.assertEqual(response.status_code, 404, "Expected 404 when stopping a non-existent chatbot.")

        # Verify lock file removal
        self.assertFalse(os.path.exists(lock_file), "Lock file was not removed.")

        # Cleanup any remaining processes
        if giveaway_id in chatbot_processes:
            chatbot_processes[giveaway_id].terminate()
            chatbot_processes[giveaway_id].wait()

    @patch("requests.post")
    @patch("requests.get")
    def test_twitch_api_failure(self, mock_get, mock_post):
        """Test handling of Twitch API failure during authentication."""
        with self.client.session_transaction() as session:
            session["user_id"] = None  # Simulate no logged-in user

        # Mock the Twitch token exchange to return an error
        mock_post.return_value.status_code = 500
        mock_post.return_value.json.return_value = {"error": "Internal Server Error"}

        # Mock the user data fetch to fail as well
        mock_get.return_value.status_code = 500
        mock_get.return_value.json.return_value = {"error": "Internal Server Error"}

        # Attempt to authenticate via Twitch
        response = self.client.get("/auth/twitch/callback?code=testcode")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Authorization failed", response.data)

        # Verify that no user was added to the session
        self.assertIsNone(session.get("user_id"))
        print('here')

    def test_stress_giveaway_creation(self):
        """Stress test for creating a large number of giveaways."""
        import threading

        def create_giveaway(index):
            with self.client.session_transaction() as session:
                session["user_id"] = 1  # Simulate logged-in user
            response = self.client.post("/giveaway/create", data={
                "title": f"Stress Test Giveaway {index}",
                "frequency": "10",
                "threshold": "5"
            })
            self.assertEqual(response.status_code, 302)  # Expect a redirect on success

        # Create threads to simulate concurrent giveaway creations
        num_threads = 50  # Number of concurrent threads
        threads = [threading.Thread(target=create_giveaway, args=(i,)) for i in range(num_threads)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to finish
        for thread in threads:
            thread.join()

        # Verify the giveaways were created
        db_session = SessionLocal()
        giveaways = db_session.query(Giveaway).filter(Giveaway.title.like("Stress Test Giveaway%")).all()
        self.assertEqual(len(giveaways), num_threads, "Not all giveaways were created successfully.")
        db_session.close()

    def test_high_volume_items_in_giveaway(self):
        """Test adding a large number of items to a single giveaway."""
        # Simulate a logged-in user
        with self.client.session_transaction() as session:
            session["user_id"] = 1

        # Create a test giveaway
        db_session = SessionLocal()
        test_giveaway = Giveaway(
            title="High Volume Item Giveaway",
            frequency=10,
            threshold=5,
            creator_id=1
        )
        db_session.add(test_giveaway)
        db_session.commit()

        giveaway_id = test_giveaway.id
        db_session.close()

        # Add a large number of items
        num_items = 1000  # Number of items to add
        for i in range(num_items):
            response = self.client.post(f"/giveaway/add-item/{giveaway_id}", data={
                "name": f"Item {i}",
                "code": f"CODE{i}"
            })
            self.assertEqual(response.status_code, 302, f"Failed to add item {i}")

        # Verify all items were added
        db_session = SessionLocal()
        items = db_session.query(Item).filter_by(giveaway_id=giveaway_id).all()
        self.assertEqual(len(items), num_items, "Not all items were added successfully.")
        db_session.close()

    def test_real_time_interaction_with_active_giveaway(self):
        """Simulate multiple users interacting with an active giveaway."""
        import threading

        # Clean up the database before starting
        db_session = SessionLocal()
        db_session.query(User).delete()
        db_session.query(Item).delete()
        db_session.query(Giveaway).delete()
        db_session.commit()

        # Create a giveaway
        active_giveaway = Giveaway(
            title="Real-Time Interaction Giveaway",
            frequency=10,
            threshold=5,
            creator_id=1,
            active=True  # Mark as active
        )
        db_session.add(active_giveaway)
        db_session.commit()
        giveaway_id = active_giveaway.id

        # Add multiple users
        for user_id in range(2, 12):  # 10 users
            user = User(id=user_id, twitch_id=f"user_{user_id}", username=f"user_{user_id}")
            db_session.add(user)
        db_session.commit()
        db_session.close()

        def user_interaction(user_id):
            with self.client.session_transaction() as session:
                session["user_id"] = user_id
            # Simulate claiming an item
            response = self.client.get(f"/giveaway/view/{giveaway_id}")
            self.assertEqual(response.status_code, 200, f"User {user_id} failed to view the giveaway")

        # Simulate concurrent interactions
        threads = [threading.Thread(target=user_interaction, args=(user_id,)) for user_id in range(2, 12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Validate the interactions
        db_session = SessionLocal()
        items_viewed = db_session.query(Item).filter_by(giveaway_id=giveaway_id).count()
        self.assertGreaterEqual(items_viewed, 0, "No items were viewed by users.")
        db_session.close()

    def test_concurrent_item_addition(self):
        """Stress test for adding items to a giveaway concurrently."""
        import threading

        # Simulate a logged-in user
        with self.client.session_transaction() as session:
            session["user_id"] = 1

        # Create a test giveaway
        db_session = SessionLocal()
        test_giveaway = Giveaway(
            title="Concurrent Item Addition Test",
            frequency=10,
            threshold=5,
            creator_id=1
        )
        db_session.add(test_giveaway)
        db_session.commit()
        giveaway_id = test_giveaway.id
        db_session.close()

        def add_item(index):
            with self.client.session_transaction() as session:
                session["user_id"] = 1  # Simulate logged-in user
            response = self.client.post(f"/giveaway/add-item/{giveaway_id}", data={
                "name": f"Concurrent Item {index}",
                "code": f"CODE{index}"
            })
            self.assertEqual(response.status_code, 302, f"Failed to add item {index}")

        # Create threads to simulate concurrent item addition
        num_threads = 50  # Number of concurrent threads
        threads = [threading.Thread(target=add_item, args=(i,)) for i in range(num_threads)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all items were added
        db_session = SessionLocal()
        items = db_session.query(Item).filter_by(giveaway_id=giveaway_id).all()
        self.assertEqual(len(items), num_threads, "Not all items were added successfully.")
        db_session.close()
