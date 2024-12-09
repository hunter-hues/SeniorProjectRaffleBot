import pytest
from app import app as flask_app
from models import Base, engine, SessionLocal


@pytest.fixture(scope="session")
def app():
    """Provide the Flask app for testing."""
    yield flask_app


@pytest.fixture(scope="session")
def db_setup():
    """
    Set up the test database schema once per session.
    Drops and recreates the database tables before tests start.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)  # Clean up the database after the session


@pytest.fixture(autouse=True)
def reset_database(db_setup):
    session = SessionLocal()
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(f"DELETE FROM {table.name}")
    session.commit()
    session.close()

