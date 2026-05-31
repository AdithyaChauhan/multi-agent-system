import os
import uuid
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi.responses import RedirectResponse

from fastapi import FastAPI, HTTPException, Header, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

from app.db.database import Base, SessionLocal, engine

from app.models.user import User
from app.models.session import Session
from app.models.message import Message
from app.models.order import Order
from app.models.product import Product
from app.models.review import Review
from app.models.spec import Spec

from app.agents.router import router_graph

from app.schemas.chat import ChatRequest, MessageResponse, SessionMessagesResponse, ChatResponse
from app.core.logger import get_logger, set_request_id, get_request_id
from app.core.config import SESSION_EXPIRY_MINUTES
from app.core.jwt_utils import verify_access_token

# Import auth router
from app.api.auth import router as auth_router

# from app.db.seed import seed_demo_data
# from app.db.seed_products import seed_demo_products
# from app.db.seed_reviews_specs import seed_reviews_and_specs

from starlette.middleware.sessions import SessionMiddleware
import secrets
from fastapi.staticfiles import StaticFiles


from langchain_core.tracers.context import collect_runs

# Per-session product preference store (in-memory, single-process).
# Persists the last extracted product subcategory across turns so the
# subcategory-persistence guard in extract_preferences has something to compare
# against. Order/support turns don't overwrite it — only product turns with a
# real subcategory update the store.
_session_prefs: dict[str, dict] = {}

Base.metadata.create_all(bind=engine)

# seed_demo_data()
# seed_demo_products()
# seed_reviews_and_specs()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events"""
    logger.info("Application startup — pre-warming prompt cache")
    from app.core.prompt_loader import load_prompt, PROMPT_VERSIONS
    for name, version in PROMPT_VERSIONS.items():
        text, _ = load_prompt(name, version)
        status = "ok" if text else "FAILED"
        logger.info(f"Prompt pre-warm | {name} | {status}")
    yield
    logger.info("Application shutdown")


app = FastAPI(
    title="Multi-Agent E-commerce System",
    version="1.0.0",
    lifespan=lifespan
)


# Session middleware (required for OAuth)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include auth router
app.include_router(auth_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


logger = get_logger("app.main")


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = set_request_id()
    logger.info(f"request_id={request_id} | method={request.method} | path={request.url.path} | REQUEST RECEIVED")
    response = await call_next(request)
    logger.info(f"request_id={request_id} | status={response.status_code} | RESPONSE RETURNED")
    response.headers["X-Request-ID"] = request_id
    return response


def get_current_user_id(request: Request) -> str:
    """
    Extract user_id from JWT token or X-User-ID header
    
    Priority:
    1. JWT token (Authorization: Bearer <token>)
    2. X-User-ID header (for testing/development)
    3. Anonymous user (if neither provided)
    """
    # Try JWT token first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        payload = verify_access_token(token)
        if payload:
            logger.info(f"request_id={get_request_id()} | Authenticated via JWT | user_id={payload.get('sub')}")
            return payload.get("sub")
        else:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Fallback to X-User-ID for testing
    user_id = request.headers.get("x-user-id")
    if user_id:
        logger.warning(f"request_id={get_request_id()} | Using X-User-ID header (development mode) | user_id={user_id}")
        return user_id
    
    # Allow anonymous users
    anon_user_id = f"anon-{str(uuid.uuid4())}"
    logger.info(f"request_id={get_request_id()} | Anonymous user | user_id={anon_user_id}")
    return anon_user_id


def get_or_create_user(db, user_id: str) -> User:
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        logger.info(f"request_id={get_request_id()} | Creating new user | user_id={user_id}")
        user = User(user_id=user_id)
        db.add(user)
        db.flush()
    return user


def get_or_create_session(db, session_id: Optional[str], user_id: str) -> Session:
    if session_id:
        session = db.query(Session).filter(Session.session_id == session_id).first()
        if not session:
            logger.info(f"request_id={get_request_id()} | Creating new session with provided id | session_id={session_id}")
            session = Session(session_id=session_id, user_id=user_id)
            db.add(session)
            db.flush()
            return session

        expiry_cutoff = datetime.now(timezone.utc) - timedelta(minutes=SESSION_EXPIRY_MINUTES)
        if session.last_active_at < expiry_cutoff:
            logger.warning(f"request_id={get_request_id()} | Session expired, starting fresh | session_id={session_id}")
            new_session = Session(session_id=str(uuid.uuid4()), user_id=user_id)
            db.add(new_session)
            db.flush()
            return new_session

        session.last_active_at = datetime.now(timezone.utc)
        db.flush()
        logger.info(f"request_id={get_request_id()} | Session resumed | session_id={session_id}")
        return session
    
    session = Session(
        session_id=str(uuid.uuid4()),
        user_id=user_id
    )
    db.add(session)
    db.flush()
    logger.info(f"request_id={get_request_id()} | New session created | session_id={session.session_id}")
    return session

def load_conversation_history(db, session_id: str, limit: int = 12) -> list:
    """Load the most recent conversation messages for a session."""
    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    messages.reverse()  # Return in chronological order
    return [{"role": msg.role, "content": msg.content} for msg in messages]


@app.get("/")
def root():
    """Redirect root to chat interface"""
    return RedirectResponse(url="/static/chat.html")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat", response_model=ChatResponse)
def chat(
    request_obj: Request,
    chat_request: ChatRequest,
    response: Response,
    x_session_id: Optional[str] = Header(default=None)
):
    # Get user_id from JWT or X-User-ID header or anonymous
    user_id = get_current_user_id(request_obj)
    
    logger.info(f"request_id={get_request_id()} | user_id={user_id} | message={chat_request.message}")

    db = SessionLocal()

    try:
        user = get_or_create_user(db, user_id)
        session = get_or_create_session(db, x_session_id or chat_request.session_id, user_id)

        new_message = Message(
            session_id=session.session_id,
            role="user",
            content=chat_request.message
        )
        db.add(new_message)
        db.commit()

        logger.info(f"request_id={get_request_id()} | User message stored | session_id={session.session_id}")

# Invoke the router graph with LangSmith tracking
        logger.info(f"request_id={get_request_id()} | Invoking router")

        conversation_history = load_conversation_history(db, session.session_id)
        logger.info(f"request_id={get_request_id()} | Loaded {len(conversation_history)} history messages")

        invoke_state: dict = {
            "user_message": chat_request.message,
            "user_id": user_id,
            "session_id": session.session_id,
            "conversation_history": conversation_history,
        }
        prior_prefs = _session_prefs.get(session.session_id)
        if prior_prefs:
            invoke_state["preferences"] = prior_prefs
            logger.info(f"request_id={get_request_id()} | Injecting prior prefs | subcategory={prior_prefs.get('subcategory')}")

        with collect_runs() as cb:
            graph_result = router_graph.invoke(
                invoke_state,
                config={
                    "tags": [f"user:{user_id}", f"session:{session.session_id}"],
                    "metadata": {
                        "user_id": user_id,
                        "session_id": session.session_id,
                        "request_id": get_request_id(),
                    },
                    "run_name": f"chat_request_{get_request_id()[:8]}"
                }
            )
        
        langsmith_run_id = str(cb.traced_runs[0].id) if cb.traced_runs else None
        logger.info(f"request_id={get_request_id()} | langsmith_run_id={langsmith_run_id}")

        
        final_response = graph_result.get("final_response", "Something went wrong.")
        logger.info(f"request_id={get_request_id()} | Graph completed | final_response_preview={final_response[:80]}")

        # Persist product preferences for next turn — only when a real subcategory was extracted.
        # Order/support turns return no preferences, so prior product context is preserved.
        new_prefs = graph_result.get("preferences")
        if new_prefs and new_prefs.get("subcategory"):
            _session_prefs[session.session_id] = new_prefs
            logger.info(f"request_id={get_request_id()} | Stored prefs | subcategory={new_prefs.get('subcategory')}")

        # Store the assistant response
        assistant_message = Message(
            session_id=session.session_id,
            role="assistant",
            content=final_response,
            langsmith_run_id=langsmith_run_id
        )
        db.add(assistant_message)
        db.commit()

        logger.info(f"request_id={get_request_id()} | Assistant message stored")

        response.headers["X-Session-ID"] = session.session_id
        response.headers["X-User-ID"] = user_id

        return ChatResponse(
            session_id=session.session_id,
            user_id=user_id,
            response=final_response
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"request_id={get_request_id()} | ERROR | {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.get("/messages/{session_id}", response_model=SessionMessagesResponse)
def get_session_messages(session_id: str):
    db = SessionLocal()

    try:
        session = db.query(Session).filter(Session.session_id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        messages = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
            .all()
        )

        return SessionMessagesResponse(
            session_id=session_id,
            user_id=session.user_id,
            messages=messages
        )

    finally:
        db.close()