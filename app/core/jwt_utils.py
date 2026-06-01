"""JWT token generation and validation"""

import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))


def create_access_token(user_id: str, email: str, name: str) -> str:
    """
    Create a JWT access token

    Args:
        user_id: User's unique identifier (google_id)
        email: User's email
        name: User's display name

    Returns:
        Encoded JWT token
    """
    expire = datetime.utcnow() + timedelta(hours=EXPIRATION_HOURS)

    payload = {
        "sub": user_id,  # Subject (user_id)
        "email": email,
        "name": name,
        "exp": expire,
        "iat": datetime.utcnow(),
    }

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token


def verify_access_token(token: str) -> Optional[dict]:
    """
    Verify and decode a JWT token

    Args:
        token: JWT token string

    Returns:
        Decoded payload if valid, None if invalid
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
