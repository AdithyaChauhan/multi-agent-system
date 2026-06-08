import os
import re
import threading
import uuid
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi.responses import RedirectResponse

from fastapi import FastAPI, HTTPException, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from app.db.database import Base, SessionLocal, engine

from app.models.user import User
from app.models.session import Session
from app.models.message import Message

from app.agents.router import router_graph
from app.agents.order_agent import order_agent_graph
from app.tools.support_tools import create_support_ticket

_session_preferences: dict = {}

_SAFETY_KEYWORDS = {
    "fire",
    "smoke",
    "burning",
    "burn",
    "burnt",
    "electric shock",
    "electrocuted",
    "injury",
    "injured",
    "injuring",
    "hurt",
    "hurting",
    "wound",
    "wounded",
    "bleeding",
    "poison",
    "poisoned",
    "toxic",
    "choking",
    "choke",
    "unconscious",
    "hospital",
    "ambulance",
    "emergency services",
    "call 911",
    "danger",
}

_SAFETY_RESPONSE = (
    "We take safety seriously. If you're in immediate danger, please call emergency services. "
    "We've flagged your message and a human team member will follow up with you."
)


def _is_safety_emergency(message: str) -> bool:
    lowered = message.lower()
    for kw in _SAFETY_KEYWORDS:
        # Match whole-word only; exclude hyphenated brand names (e.g. "Fire-Boltt")
        pattern = r"(?<![a-zA-Z])" + re.escape(kw) + r"(?![a-zA-Z\-])"
        if re.search(pattern, lowered):
            return True
    return False


from app.schemas.chat import ChatRequest, SessionMessagesResponse, ChatResponse
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
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.core.metrics import http_requests_total, http_request_duration_seconds

_LANGSMITH_CLIENT = None
_LANGSMITH_CLIENT_LOCK = threading.Lock()


def _get_langsmith_client():
    global _LANGSMITH_CLIENT
    if _LANGSMITH_CLIENT is None:
        with _LANGSMITH_CLIENT_LOCK:
            if _LANGSMITH_CLIENT is None:
                try:
                    from langsmith import Client

                    lc_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
                    if lc_key:
                        _LANGSMITH_CLIENT = Client(api_key=lc_key)
                except Exception:
                    pass
    return _LANGSMITH_CLIENT


def _submit_turn_feedback(run_id: str, user_message: str, response_text: str) -> None:
    """
    Submit lightweight per-turn feedback scores to LangSmith via create_feedback().
    Runs in a daemon thread so it never blocks the HTTP response.

    Dimensions:
      - response_quality : 1.0 if response is non-trivial and error-free, else 0.0
      - relevance        : 1.0 if agent gave a substantive reply, 0.5 if generic fallback
      - conciseness      : 1.0 if ≤ 800 chars, decays linearly above that
    """
    try:
        client = _get_langsmith_client()
        if not client or not run_id:
            return

        text = response_text.strip()
        text_lower = text.lower()

        # response_quality: non-trivial length + no server error strings
        error_phrases = ["something went wrong", "internal server error", "traceback", "http 500"]
        quality = 0.0 if len(text) < 20 or any(e in text_lower for e in error_phrases) else 1.0

        # relevance: penalise the generic "I didn't understand" fallback
        generic_fallbacks = [
            "i didn't quite understand",
            "are you looking for a product",
        ]
        relevance = 0.5 if any(f in text_lower for f in generic_fallbacks) else 1.0

        # conciseness: full score up to 800 chars, linear decay to 0 at 3000 chars
        conciseness = max(0.0, min(1.0, 1.0 - (len(text) - 800) / 2200)) if len(text) > 800 else 1.0

        for key, score in [
            ("response_quality", quality),
            ("relevance", relevance),
            ("conciseness", conciseness),
        ]:
            client.create_feedback(run_id=run_id, key=key, score=round(score, 4))

    except Exception:
        pass  # feedback is non-critical — never let it affect the user response


Base.metadata.create_all(bind=engine)

# seed_demo_data()
# seed_demo_products()
# seed_reviews_and_specs()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup")
    from app.core.prompt_loader import prewarm_prompts

    prewarm_prompts()
    yield
    logger.info("Application shutdown")


app = FastAPI(title="Multi-Agent E-commerce System", version="1.0.0", lifespan=lifespan)


# Session middleware (required for OAuth)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32)))

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
    import time as _time

    request_id = set_request_id()
    _t0 = _time.perf_counter()

    if request.url.path != "/metrics":
        logger.info(f"request_id={request_id} | method={request.method} | path={request.url.path} | REQUEST RECEIVED")

    response = await call_next(request)
    _duration = _time.perf_counter() - _t0

    if request.url.path != "/metrics":
        logger.info(f"request_id={request_id} | status={response.status_code} | RESPONSE RETURNED")
        http_requests_total.labels(
            method=request.method,
            endpoint=request.url.path,
            status_code=str(response.status_code),
        ).inc()
        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=request.url.path,
        ).observe(_duration)

    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/metrics", include_in_schema=False)
def metrics_endpoint():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


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
            logger.info(
                f"request_id={get_request_id()} | Creating new session with provided id | session_id={session_id}"
            )
            session = Session(session_id=session_id, user_id=user_id)
            db.add(session)
            db.flush()
            return session

        expiry_cutoff = datetime.now(timezone.utc) - timedelta(minutes=SESSION_EXPIRY_MINUTES)
        last_active = session.last_active_at
        # SQLite returns naive datetimes; make it aware so comparison works on both dialects
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=timezone.utc)
        if last_active < expiry_cutoff:
            logger.warning(
                f"request_id={get_request_id()} | Session expired | session_id={session_id} | last_active_at={session.last_active_at}"
            )
            raise HTTPException(
                status_code=410,
                detail=f"Session expired. Last activity was more than {SESSION_EXPIRY_MINUTES} minutes ago. Start a new session.",
            )

        session.last_active_at = datetime.now(timezone.utc)
        db.flush()
        logger.info(f"request_id={get_request_id()} | Session resumed | session_id={session_id}")
        return session

    session = Session(session_id=str(uuid.uuid4()), user_id=user_id)
    db.add(session)
    db.flush()
    logger.info(f"request_id={get_request_id()} | New session created | session_id={session.session_id}")
    return session


def load_conversation_history(db, session_id: str, limit: int = 20) -> list:
    """Load the most recent messages for the session in chronological order."""
    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{"role": msg.role, "content": msg.content} for msg in reversed(messages)]


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
    x_session_id: Optional[str] = Header(default=None),
):
    # Get user_id from JWT or X-User-ID header or anonymous
    user_id = get_current_user_id(request_obj)

    logger.info(f"request_id={get_request_id()} | user_id={user_id} | message={chat_request.message}")

    db = SessionLocal()

    try:
        get_or_create_user(db, user_id)
        session = get_or_create_session(db, x_session_id or chat_request.session_id, user_id)

        new_message = Message(session_id=session.session_id, role="user", content=chat_request.message)
        db.add(new_message)
        db.commit()

        logger.info(f"request_id={get_request_id()} | User message stored | session_id={session.session_id}")

        # Safety gate — exits before any agent or LLM call
        if _is_safety_emergency(chat_request.message):
            logger.warning(
                f"request_id={get_request_id()} | SAFETY_GATE triggered | user_id={user_id} | message={chat_request.message[:100]}"
            )
            create_support_ticket(
                user_id=user_id,
                severity="critical",
                category="other",
                description=f"[SAFETY_ALERT] {chat_request.message[:500]}",
                safety_alert=True,
            )
            assistant_message = Message(session_id=session.session_id, role="assistant", content=_SAFETY_RESPONSE)
            db.add(assistant_message)
            db.commit()
            response.headers["X-Session-ID"] = session.session_id
            response.headers["X-User-ID"] = user_id
            return ChatResponse(session_id=session.session_id, user_id=user_id, response=_SAFETY_RESPONSE)

        # Invoke the router graph with LangSmith tracking
        logger.info(f"request_id={get_request_id()} | Invoking router")

        conversation_history = load_conversation_history(db, session.session_id)
        logger.info(f"request_id={get_request_id()} | Loaded {len(conversation_history)} history messages")

        with collect_runs() as cb:
            graph_result = router_graph.invoke(
                {
                    "user_message": chat_request.message,
                    "user_id": user_id,
                    "session_id": session.session_id,
                    "conversation_history": conversation_history,
                    "preferences": _session_preferences.get(session.session_id),
                },
                config={
                    "tags": [f"user:{user_id}", f"session:{session.session_id}"],
                    "metadata": {
                        "user_id": user_id,
                        "session_id": session.session_id,
                        "request_id": get_request_id(),
                        # thread_id groups all turns of one session for LangSmith
                        # thread-level evaluators (Knowledge Retention, User Satisfaction, etc.)
                        "thread_id": session.session_id,
                    },
                    "run_name": f"chat_request_{get_request_id()[:8]}",
                },
            )

        langsmith_run_id = str(cb.traced_runs[0].id) if cb.traced_runs else None
        logger.info(f"request_id={get_request_id()} | langsmith_run_id={langsmith_run_id}")

        if graph_result.get("preferences"):
            _session_preferences[session.session_id] = graph_result["preferences"]

        # Support agent detected a bare order lookup — re-invoke order agent directly
        if graph_result.get("reroute_to_order"):
            support_order = graph_result.get("support_order") or {}
            logger.info(
                f"request_id={get_request_id()} | Rerouting to order agent | order_id={support_order.get('order_id')}"
            )
            order_result = order_agent_graph.invoke(
                {
                    "user_message": chat_request.message,
                    "user_id": user_id,
                    "session_id": session.session_id,
                    "conversation_history": conversation_history,
                    "order_id": support_order.get("order_id"),
                }
            )
            final_response = order_result.get("final_response", "Something went wrong.")
        else:
            final_response = graph_result.get("final_response", "Something went wrong.")
        logger.info(f"request_id={get_request_id()} | Graph completed | final_response_preview={final_response[:80]}")

        # Submit per-turn feedback scores to LangSmith (fire-and-forget, non-blocking)
        if langsmith_run_id:
            threading.Thread(
                target=_submit_turn_feedback,
                args=(langsmith_run_id, chat_request.message, final_response),
                daemon=True,
            ).start()

        # Store the assistant response
        assistant_message = Message(
            session_id=session.session_id, role="assistant", content=final_response, langsmith_run_id=langsmith_run_id
        )
        db.add(assistant_message)
        db.commit()

        logger.info(f"request_id={get_request_id()} | Assistant message stored")

        response.headers["X-Session-ID"] = session.session_id
        response.headers["X-User-ID"] = user_id

        return ChatResponse(session_id=session.session_id, user_id=user_id, response=final_response)

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

        messages = db.query(Message).filter(Message.session_id == session_id).order_by(Message.created_at.asc()).all()

        return SessionMessagesResponse(session_id=session_id, user_id=session.user_id, messages=messages)

    finally:
        db.close()
