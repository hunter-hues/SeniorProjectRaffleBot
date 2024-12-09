from models import Base, engine

def setup_module(module):
    """Set up the test database schema."""
    Base.metadata.create_all(bind=engine)

def teardown_module(module):
    """Tear down the test database schema."""
    Base.metadata.drop_all(bind=engine)
