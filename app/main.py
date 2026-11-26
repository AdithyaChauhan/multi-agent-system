import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi.responses import RedirectResponse, StreamingResponse

from fastapi import FastAPI, HTTPException, Header, Request, Response
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from app.db.database import Base, SessionLocal, engine
from app.db.migrate_schema import ensure_support_ticket_priority_column

from app.models.user import User
from app.models.session import Session
from app.models.message import Message

from langgraph.types import Command

from app.agents.router import new_turn, router_graph

from app.schemas.chat import ChatRequest, SessionMessagesResponse, ChatResponse
from app.core.logger import get_logger, set_request_id, get_request_id
from app.core.config import SESSION_EXPIRY_MINUTES
from app.core import limits
from app.core.llm import ModelsUnavailable
from app.core.redact import install_trace_anonymizer
from app.core.jwt_utils import verify_access_token

# Import auth router
from app.api.auth import router as auth_router

from app.db.seed import seed_demo_data

# from app.db.seed_products import seed_demo_products
# from app.db.seed_reviews_specs import seed_reviews_and_specs

from starlette.middleware.sessions import SessionMiddleware
import secrets
from fastapi.staticfiles import StaticFiles


from langchain_core.tracers.context import collect_runs
from langchain_core.tracers.run_collector import RunCollectorCallbackHandler
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.core.metrics import chat_turn_seconds, chat_turns_total, http_requests_total, http_request_duration_seconds

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
ensure_support_ticket_priority_column()

seed_demo_data()
# seed_demo_products()
# seed_reviews_and_specs()


def _warm_search() -> None:
    """Load the embedding model in the background, so the first shopper doesn't wait for it."""
    from app.core.config import PRODUCT_SEARCH
    from app.search import hybrid

    if PRODUCT_SEARCH == "hybrid" and hybrid.hybrid_available():
        try:
            hybrid._query_vector("warm up")
            logger.info("hybrid search ready")
        except Exception as exc:  # the type search still works without it
            logger.warning(f"hybrid search warm-up failed: {type(exc).__name__}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup")
    threading.Thread(target=_warm_search, daemon=True).start()
    yield
    logger.info("Application shutdown")


install_trace_anonymizer()  # before the first traced run

app = FastAPI(title="Multi-Agent E-commerce System", version="1.0.0", lifespan=lifespan)

# The mock carrier API (order tracking) runs inside the app at /carrier on single-service hosts
# (Render free tier); docker compose still runs it as its own container. Demo data only.
from mock_services.carrier_api import app as carrier_app  # noqa: E402

app.mount("/carrier", carrier_app)


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


_enable_request_logging = os.getenv("CI", "").lower() not in {"1", "true", "yes"}

if _enable_request_logging:

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        import time as _time

        request_id = set_request_id()
        _t0 = _time.perf_counter()

        if request.url.path != "/metrics":
            logger.info(
                f"request_id={request_id} | method={request.method} | path={request.url.path} | REQUEST RECEIVED"
            )

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
    2. X-User-ID header, only when ALLOW_X_USER_ID=true (tests and eval harnesses)
    3. Anonymous user
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

    # X-User-ID names the caller without proof, so it's honoured only in tests and eval harnesses
    # (ALLOW_X_USER_ID=true). Anywhere else it would let anyone act as any user.
    user_id = request.headers.get("x-user-id") if os.getenv("ALLOW_X_USER_ID", "").lower() == "true" else None
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


@app.api_route("/health", methods=["GET", "HEAD"])  # uptime monitors ping with HEAD
def health():
    return {"status": "ok"}


def check_resume(session: Session, user_id: str, thread: dict) -> Optional[str]:
    """A Yes/No answer resumes the paused graph only for the signed-in owner of the conversation, and
    only while a question is actually waiting. Returns the reason to refuse, or None."""
    if user_id.startswith("anon-") or session.user_id != user_id:
        logger.warning(f"request_id={get_request_id()} | resume refused: not this user's conversation")
        return "Please sign in to the account this conversation belongs to."
    if not router_graph.get_state(thread).interrupts:
        return "There's nothing waiting for your confirmation. What would you like to do?"
    return None


def _store_reply(db, session: Session, text: str, run_id=None) -> None:
    db.add(Message(session_id=session.session_id, role="assistant", content=text, langsmith_run_id=run_id))
    db.commit()
    logger.info(f"request_id={get_request_id()} | Assistant message stored")


@dataclass
class Turn:
    """One chat turn, ready to run: who, which conversation, and the graph input (or why not)."""

    user_id: str
    session: Session
    config: dict
    graph_input: object = None
    refusal: Optional[str] = None
    endpoint: str = "/chat"
    started: float = field(default_factory=time.perf_counter)


def _observe(turn: Turn, outcome: str) -> None:
    """Count how the turn ended and time it, start to reply (Grafana's turn panels)."""
    chat_turns_total.labels(endpoint=turn.endpoint, outcome=outcome).inc()
    chat_turn_seconds.labels(endpoint=turn.endpoint).observe(time.perf_counter() - turn.started)


def start_turn(db, request_obj: Request, chat_request: ChatRequest, x_session_id: Optional[str]) -> Turn:
    """Shared by /chat and /chat/stream: user, session, the stored user message and the graph input."""
    user_id = get_current_user_id(request_obj)
    logger.info(f"request_id={get_request_id()} | user_id={user_id} | message={chat_request.message}")
    get_or_create_user(db, user_id)
    session = get_or_create_session(db, x_session_id or chat_request.session_id, user_id)
    db.add(Message(session_id=session.session_id, role="user", content=chat_request.message))
    db.commit()
    logger.info(f"request_id={get_request_id()} | User message stored | session_id={session.session_id}")

    # One checkpointed graph thread per chat session: search filters carry over between turns and
    # survive restarts, and a paused question (cancel this order?) waits there for the answer.
    thread = {"configurable": {"thread_id": session.session_id}}
    config = {
        **thread,
        "tags": [f"user:{user_id}", f"session:{session.session_id}"],
        "metadata": {
            "user_id": user_id,
            "session_id": session.session_id,
            "request_id": get_request_id(),
            # thread_id groups all turns of one session for LangSmith thread-level evaluators
            "thread_id": session.session_id,
        },
        "run_name": f"chat_request_{get_request_id()[:8]}",
    }
    turn = Turn(user_id=user_id, session=session, config=config, endpoint=request_obj.url.path)
    client_ip = request_obj.client.host if request_obj.client else None
    turn.refusal = limits.check_turn(limits.caller_key(user_id, client_ip))
    if turn.refusal:
        return turn
    if chat_request.confirm is None:
        history = load_conversation_history(db, session.session_id)
        turn.graph_input = new_turn(
            chat_request.message, user_id, session.session_id, history, filter_edit=chat_request.remove_filter
        )
    else:
        turn.refusal = check_resume(session, user_id, thread)
        if not turn.refusal:
            turn.graph_input = Command(resume={"confirm": chat_request.confirm, "user_id": user_id})
    return turn


def finish_turn(db, turn: Turn, chat_request: ChatRequest, graph_result: dict, run_id=None) -> ChatResponse:
    """Shared by /chat and /chat/stream: the reply (or the paused question), stored and returned."""
    paused = graph_result.get("__interrupt__") or []
    action = paused[0].value if paused else None
    text = (action or {}).get("question") or graph_result.get("final_response") or "Something went wrong."
    logger.info(f"request_id={get_request_id()} | Graph completed | final_response_preview={text[:80]}")
    if run_id:  # per-turn feedback scores to LangSmith, fire-and-forget
        threading.Thread(target=_submit_turn_feedback, args=(run_id, chat_request.message, text), daemon=True).start()
    _store_reply(db, turn.session, text, run_id)
    _observe(turn, "answered")
    return ChatResponse(
        session_id=turn.session.session_id,
        user_id=turn.user_id,
        response=text,
        action=action,
        run_id=run_id,
        active_filters=graph_result.get("active_filters"),
        products=product_cards(graph_result) if not action else None,
    )


CARD_FIELDS = ("product_id", "title", "brand", "price", "rating", "image", "link")


def product_cards(graph_result: dict) -> Optional[list]:
    """The products the reply lists (its top 3), with what a card needs: photo, price, rating, link."""
    shown = (graph_result.get("ranked_products") or [])[:3]
    return [{k: p.get(k) for k in CARD_FIELDS} for p in shown] or None


def _refused(db, turn: Turn, outcome: str = "") -> ChatResponse:
    _store_reply(db, turn.session, turn.refusal)
    limited = turn.refusal in (limits.RATE_LIMITED, limits.DAILY_LIMIT)
    _observe(turn, outcome or ("limited" if limited else "refused"))
    return ChatResponse(session_id=turn.session.session_id, user_id=turn.user_id, response=turn.refusal)


BUSY_REPLY = "I'm getting a lot of questions right now and couldn't answer this one. " "Please try again in a minute."


def _busy(db, turn: Turn, error: Exception) -> ChatResponse:
    """Every model in the fallback chain failed: a normal reply saying so, never an error page."""
    logger.error(f"request_id={get_request_id()} | MODELS_UNAVAILABLE | {error} | cause={error.__cause__!r}"[:500])
    db.rollback()
    turn.refusal = BUSY_REPLY
    return _refused(db, turn, "busy")


@app.post("/chat", response_model=ChatResponse)
def chat(
    request_obj: Request,
    chat_request: ChatRequest,
    response: Response,
    x_session_id: Optional[str] = Header(default=None),
):
    db = SessionLocal()
    turn = None
    try:
        turn = start_turn(db, request_obj, chat_request, x_session_id)
        response.headers["X-Session-ID"] = turn.session.session_id
        response.headers["X-User-ID"] = turn.user_id
        if turn.refusal:
            return _refused(db, turn)
        try:
            with collect_runs() as cb:
                graph_result = router_graph.invoke(turn.graph_input, config=turn.config)
        except ModelsUnavailable as e:
            return _busy(db, turn, e)
        run_id = str(cb.traced_runs[0].id) if cb.traced_runs else None
        logger.info(f"request_id={get_request_id()} | langsmith_run_id={run_id}")
        return finish_turn(db, turn, chat_request, graph_result, run_id)

    except HTTPException:
        db.rollback()
        raise
    except OperationalError as e:
        logger.error(f"request_id={get_request_id()} | DB_ERROR | {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="We're experiencing technical difficulties. Please try again in a moment.",
        )
    except Exception as e:
        logger.error(f"request_id={get_request_id()} | ERROR | {str(e)}")
        db.rollback()
        if turn:
            _observe(turn, "error")
        raise HTTPException(
            status_code=500,
            detail="Something went wrong on our end. Please try again.",
        )
    finally:
        db.close()


# What the chat window shows while a step runs. Only these labels and the final reply are streamed,
# never raw model output, so streaming can't bypass a guardrail.
STEP_LABELS = {
    "classify": "Understanding your message…",
    "extract_preferences": "Working out what you're looking for…",
    "search": "Searching products…",
    "loosen": "Nothing exact yet, widening the search…",
    "rank_products": "Picking the best matches…",
    "find_order": "Checking your order…",
    "order_status": "Getting the latest tracking…",
    "draft_resolution": "Writing a reply…",
    "open_ticket": "Creating a support ticket…",
    "notify": "Letting our support team know…",
    "cancel_order": "Cancelling your order…",
    "qa_think": "Reading the product details…",
    "qa_tools": "Looking up product facts…",
}


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/chat/stream")
def chat_stream(
    request_obj: Request,
    chat_request: ChatRequest,
    x_session_id: Optional[str] = Header(default=None),
):
    """Same turn as /chat, as server-sent events: `step` labels while the graph runs, then one `reply`
    event whose data is the ChatResponse /chat would return (or an `error` event)."""
    db = SessionLocal()
    try:
        turn = start_turn(db, request_obj, chat_request, x_session_id)  # 401 / 410 are raised here
    except Exception:
        db.rollback()
        db.close()
        raise

    def events():
        try:
            if turn.refusal:
                yield _event("reply", _refused(db, turn).model_dump())
                return
            last = None
            # collect_runs() keeps its collector in a context variable, and Starlette steps this
            # generator from worker threads with different contexts: pass the collector directly.
            collector = RunCollectorCallbackHandler()
            config = {**turn.config, "callbacks": [collector]}
            for _, chunk in router_graph.stream(turn.graph_input, config=config, stream_mode="tasks", subgraphs=True):
                label = STEP_LABELS.get(chunk.get("name")) if "input" in chunk else None  # a task starting
                if label and label != last:
                    last = label
                    yield _event("step", {"label": label})
            run_id = str(collector.traced_runs[0].id) if collector.traced_runs else None
            state = router_graph.get_state(turn.config)
            result = {**state.values, "__interrupt__": list(state.interrupts)}
            yield _event("reply", finish_turn(db, turn, chat_request, result, run_id).model_dump())
        except ModelsUnavailable as e:
            yield _event("reply", _busy(db, turn, e).model_dump())
        except Exception as e:
            logger.error(f"request_id={get_request_id()} | STREAM_ERROR | {str(e)}")
            db.rollback()
            _observe(turn, "error")
            yield _event("error", {"detail": "Something went wrong on our end. Please try again."})
        finally:
            db.close()

    headers = {"X-Session-ID": turn.session.session_id, "X-User-ID": turn.user_id, "Cache-Control": "no-cache"}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


class FeedbackRequest(BaseModel):
    run_id: str
    score: int  # 1 = thumbs up, -1 = thumbs down


@app.post("/api/feedback")
def submit_feedback(body: FeedbackRequest):
    """Submit explicit user thumbs-up/down feedback to LangSmith for the given run."""
    client = _get_langsmith_client()
    if not client:
        raise HTTPException(status_code=503, detail="Feedback service unavailable")
    try:
        client.create_feedback(run_id=body.run_id, key="user_feedback", score=body.score)
        return {"ok": True}
    except Exception as e:
        logger.error(f"LangSmith feedback error | run_id={body.run_id} | error={e}")
        raise HTTPException(status_code=500, detail="Failed to submit feedback")


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
