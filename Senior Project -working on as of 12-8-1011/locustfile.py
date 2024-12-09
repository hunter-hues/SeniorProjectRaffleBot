from locust import HttpUser, task

class WebsiteUser(HttpUser):
    host = "http://localhost:5000"  # Replace with your Flask app's base URL

    @task
    def view_dashboard(self):
        self.client.get("/dashboard")

    @task
    def create_giveaway(self):
        self.client.post("/giveaway/create", data={
            "title": "Load Test Giveaway",
            "frequency": "10",
            "threshold": "5"
        })
