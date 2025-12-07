from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    cards = relationship("Card", back_populates="owner", lazy="selectin")
    progress = relationship("Progress", back_populates="user", lazy="selectin")
    user_card_progress = relationship("UserCardProgress", back_populates="user", lazy="selectin")

class Card(Base):
    __tablename__ = "cards"
    id = Column(Integer, primary_key=True, index=True)
    foreign_word = Column(String, index=True)
    native_translation = Column(String)
    example = Column(String, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    is_public = Column(Boolean, default=True)  
    
    owner = relationship("User", back_populates="cards", lazy="selectin")
    user_card_progress = relationship("UserCardProgress", back_populates="card", lazy="selectin")

class Progress(Base):
    __tablename__ = "progress"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    total_cards = Column(Integer, default=0)
    completed_cards = Column(Integer, default=0)
    marked_important = Column(Integer, default=0)
    
    user = relationship("User", back_populates="progress")

class UserCardProgress(Base):
    __tablename__ = "user_card_progress"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    card_id = Column(Integer, ForeignKey("cards.id"))
    is_completed = Column(Boolean, default=False)
    completed_at = Column(DateTime, nullable=True)
    
    __table_args__ = (UniqueConstraint('user_id', 'card_id', name='unique_user_card'),)
    
    user = relationship("User", back_populates="user_card_progress")
    card = relationship("Card", back_populates="user_card_progress")