"""Abuse limits on chat turns (ADR 0015): a per-minute rate and a daily turn budget per caller.

The Groq free tier is shared by every visitor (200K tokens a day per model), so one caller can't be
allowed to use it all. Signed-in users are counted by user id, anonymous ones by client IP (an
anonymous id changes with every new session). Counts live in this process's memory: good enough
for one instance; several instances would each allow the full amount.
"""

import threading
import time
from collections import defaultdict, deque
from datetime import date
from typing import Optional

from app.core import config
from app.core.metrics import chat_limited_total

RATE_LIMITED = "You're sending messages very quickly. Please wait a few seconds and try again."
DAILY_LIMIT = "You've reached today's limit for this demo, which keeps it free for everyone. Please come back tomorrow."

_lock = threading.Lock()
_recent: dict = defaultdict(deque)  # caller -> monotonic times of turns in the last minute
_daily: dict = {}  # caller -> (date, turns)


def caller_key(user_id: str, client_ip: Optional[str]) -> str:
    if user_id and not user_id.startswith("anon-"):
        return f"user:{user_id}"
    return f"ip:{client_ip or 'unknown'}"


def check_turn(key: str) -> Optional[str]:
    """None if this turn may run (and count it), or the message to send instead."""
    now = time.monotonic()
    today = date.today()
    with _lock:
        recent = _recent[key]
        while recent and now - recent[0] > 60:
            recent.popleft()
        if len(recent) >= config.CHAT_RATE_PER_MINUTE:
            chat_limited_total.labels(limit="per_minute").inc()
            return RATE_LIMITED
        day, turns = _daily.get(key, (today, 0))
        if day != today:
            turns = 0
        if turns >= config.CHAT_TURNS_PER_DAY:
            chat_limited_total.labels(limit="per_day").inc()
            return DAILY_LIMIT
        recent.append(now)
        _daily[key] = (today, turns + 1)
    return None


def reset() -> None:
    with _lock:
        _recent.clear()
        _daily.clear()
