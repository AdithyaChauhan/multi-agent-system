from sqlalchemy import Column, String, DateTime, Enum
from sqlalchemy.sql import func
from app.db.database import Base
import enum


class AuthProvider(enum.Enum):
    """Authentication provider types"""
    GOOGLE = "google"
    DEMO = "demo"
    ANONYMOUS = "anonymous"


class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)  # Our internal ID (UUID)
    email = Column(String, unique=True, nullable=True, index=True)
    name = Column(String, nullable=True)
    
    # SSO fields
    google_id = Column(String, unique=True, nullable=True, index=True)  # From Google OAuth
    auth_provider = Column(String, default="anonymous")  # "google", "demo", "anonymous"
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())