"""OAuth authentication endpoints"""

import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from dotenv import load_dotenv

from app.core.jwt_utils import create_access_token, verify_access_token
from app.db.database import SessionLocal
from app.models.user import User
from app.core.logger import get_logger

load_dotenv()

logger = get_logger("app.api.auth")

router = APIRouter(prefix="/auth", tags=["Authentication"])

# OAuth configuration
config = Config(
    environ={
        "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID"),
        "GOOGLE_CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET"),
    }
)

oauth = OAuth(config)
oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)


@router.get("/login")
async def login(request: Request):
    """Redirect to Google OAuth login"""
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    """
    Handle OAuth callback from Google.
    Creates/updates user and issues JWT token.
    """
    try:
        # Get token from Google
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo')

        if not user_info:
            raise HTTPException(status_code=400, detail="Failed to get user info from Google")

        google_id = user_info.get('sub')
        email = user_info.get('email')
        name = user_info.get('name')

        logger.info(f"OAuth callback | email={email} | google_id={google_id}")

        # Create or update user in database
        db = SessionLocal()
        try:
            # Check by google_id OR user_id (handles users created before OAuth)
            user_id_str = f"google-{google_id}"
            user = db.query(User).filter((User.google_id == google_id) | (User.user_id == user_id_str)).first()

            if not user:
                # Create new user with user_id derived from google_id
                user_id = f"google-{google_id}"

                user = User(user_id=user_id, google_id=google_id, email=email, name=name, auth_provider="google")
                db.add(user)
                db.commit()
                db.refresh(user)
                logger.info(f"New user created | user_id={user.user_id} | email={email}")
            else:
                # Update existing user
                user.email = email
                user.name = name
                db.commit()
                logger.info(f"User updated | user_id={user.user_id} | email={email}")

            # Use user_id from database
            user_id = user.user_id

        finally:
            db.close()

        # Generate JWT token
        jwt_token = create_access_token(user_id=user_id, email=email, name=name)

        # Redirect to callback page with token
        callback_url = f"/static/callback.html?token={jwt_token}&user={email}"
        return RedirectResponse(url=callback_url)

    except Exception as e:
        logger.error(f"OAuth callback error | error={str(e)}")
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")


@router.get("/me")
async def get_current_user(request: Request):
    """Get current user from JWT token"""
    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = auth_header.replace("Bearer ", "")
    payload = verify_access_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {"user_id": payload.get("sub"), "email": payload.get("email"), "name": payload.get("name")}


@router.post("/logout")
async def logout():
    """Logout (client should delete token)"""
    return {"message": "Logged out successfully. Please delete your token."}


@router.post("/demo-login")
async def demo_login(request: Request):
    """Login with just a user_id — no password, for demo/testing"""
    body = await request.json()
    user_id = body.get("user_id", "").strip()

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            user = User(user_id=user_id, auth_provider="demo")
            db.add(user)
            db.commit()
            db.refresh(user)

        token = create_access_token(
            user_id=user.user_id,
            email=user.email or f"{user_id}@demo.com",
            name=user.name or user_id,
        )
        return {"access_token": token}
    finally:
        db.close()
