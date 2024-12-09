from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Database connection
DATABASE_URL = "sqlite:///giveaway.db"
Base = declarative_base()
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    twitch_id = Column(String, unique=True, index=True, nullable=False)  # Add `nullable=False`
    username = Column(String, unique=True, index=True, nullable=False)  # Add `nullable=False`

    giveaways = relationship("Giveaway", back_populates="creator")
    winnings = relationship("Winner", back_populates="user")

# In models.py
class Giveaway(Base):
    __tablename__ = "giveaways"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    frequency = Column(Integer, nullable=False)
    threshold = Column(Integer, nullable=False)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    active = Column(Boolean, default=False)  # New field to track active state


    creator = relationship("User", back_populates="giveaways")
    items = relationship(
        "Item", 
        back_populates="giveaway", 
        cascade="none"  # Disable cascading behavior
    )
    winners = relationship("Winner", back_populates="giveaway")

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    code = Column(String, nullable=True)
    is_won = Column(Boolean, default=False)
    giveaway_id = Column(Integer, ForeignKey("giveaways.id", ondelete="SET NULL"), nullable=True)
    winner_username = Column(String, nullable=True)

    giveaway = relationship("Giveaway", back_populates="items")

# Winner model
class Winner(Base):
    __tablename__ = "winners"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    giveaway_id = Column(Integer, ForeignKey("giveaways.id"))
    item_id = Column(Integer, ForeignKey("items.id"))

    user = relationship("User", back_populates="winnings")
    giveaway = relationship("Giveaway", back_populates="winners")
    item = relationship("Item")

# Create tables
Base.metadata.create_all(bind=engine)
