"""20-user load test (Phase 5): the path a judge takes, many times at once.

Each simulated user presses "Try as a demo shopper" (their own five orders), then walks the chat's
"things to try": a product search, a question about the cards, an order lookup, a cancel with the
Yes button, and a damage report. Then they start again as a new shopper. Think time is 5-15 s, a
person reading the cards.

Run it with eval/loadtest/run.sh (a separate app container with raised demo limits, its own database,
and alerts switched off). Besides Locust's latency and error stats, it counts how each reply was
produced, from the replies themselves and the app's /metrics:
  - busy:     the "lots of questions right now" reply (every model in the fallback chain failed);
  - limited:  the per-user rate or daily limit refused the turn;
  - answered: anything else.
Results go to $LOADTEST_OUT (default: the temp folder) as <label>_outcomes.json.
"""

import json
import os
import random
import tempfile
import threading
from pathlib import Path

from locust import SequentialTaskSet, between, events, task
from locust.contrib.fasthttp import FastHttpUser

BUSY = "getting a lot of questions right now"
LIMITED = ("sending messages very quickly", "reached today's limit")

# The chat's own suggestions come first: judges click those, so they repeat across users (and the
# answer cache sees them). The rest vary the wording the way people do.
SEARCHES = [
    "something to keep my room warm under 2000",
    "something to keep my room warm under 2000",
    "wireless mouse under 1000",
    "show me some TVs",
    "sony headphones under 3000",
    "an electric kettle",
    "air purifier for a small bedroom",
    "bluetooth speaker with good bass",
    "a steam iron under 1500",
    "4k tv from samsung",
]
FOLLOW_UPS = [
    "tell me more about the second one",
    "tell me more about the second one",
    "which one has the best rating?",
    "show me something cheaper",
]

_lock = threading.Lock()
OUTCOMES: dict = {}


def _count(step: str, outcome: str) -> None:
    with _lock:
        OUTCOMES.setdefault(step, {}).setdefault(outcome, 0)
        OUTCOMES[step][outcome] += 1


def _outcome(text: str) -> str:
    if BUSY in text:
        return "busy"
    if any(p in text for p in LIMITED):
        return "limited"
    return "answered"


class DemoPath(SequentialTaskSet):
    def on_start(self):
        self.token = None
        self.orders = []
        self.session_id = None
        r = self.client.post("/auth/demo-shopper", name="0 demo shopper")
        if r.status_code == 200:
            data = r.json()
            self.token, self.orders = data["access_token"], data["orders"]

    def chat(self, step: str, message: str, **extra):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        if self.session_id:
            headers["X-Session-ID"] = self.session_id
        body = {"message": message, **extra}
        with self.client.post("/chat", json=body, headers=headers, name=step, catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"HTTP {r.status_code}")
                _count(step, f"http_{r.status_code}")
                return None
            data = r.json()
            self.session_id = data.get("session_id") or self.session_id
            _count(step, _outcome(data.get("response") or ""))
            r.success()
            return data

    @task
    def search(self):
        self.chat("1 search", random.choice(SEARCHES))

    @task
    def follow_up(self):
        self.chat("2 follow-up", random.choice(FOLLOW_UPS))

    @task
    def order_status(self):
        self.chat("3 order status", "where is my TV order?")

    @task
    def cancel(self):
        data = self.chat("4 cancel", "cancel my mouse order")
        if data and (data.get("action") or {}).get("type") == "confirm_cancel":
            self.chat("5 confirm yes", "Yes, cancel it", confirm=True)

    @task
    def damage(self):
        self.chat("6 damage report", "my steam iron arrived damaged")

    @task
    def next_shopper(self):
        self.on_start()  # a new visitor: fresh shopper, fresh orders, new chat


class Shopper(FastHttpUser):
    tasks = [DemoPath]
    wait_time = between(5, 15)
    network_timeout = 60.0
    connection_timeout = 10.0


@events.test_stop.add_listener
def _save_outcomes(environment, **_):
    out_dir = Path(os.getenv("LOADTEST_OUT", tempfile.gettempdir()))
    label = os.getenv("LOADTEST_LABEL", "loadtest")
    path = out_dir / f"{label}_outcomes.json"
    path.write_text(json.dumps(OUTCOMES, indent=1), encoding="utf-8")
    print(f"reply outcomes -> {path}")
    for step in sorted(OUTCOMES):
        print(f"  {step:<18} {OUTCOMES[step]}")
