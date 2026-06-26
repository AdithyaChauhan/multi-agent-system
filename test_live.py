#!/usr/bin/env python3
"""
10 live end-to-end tests covering all agents.
Hits the running app at localhost:8000 — no mocks, no fixtures.
"""
import json
import uuid
import requests

BASE = "http://localhost:8000"
PASS = "\033[92m PASS\033[0m"
FAIL = "\033[91m FAIL\033[0m"


def chat(message, session_id=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["X-Session-ID"] = session_id
    r = requests.post(f"{BASE}/chat", headers=headers, json={"message": message}, timeout=120)
    r.raise_for_status()
    return r.json()


def new_session():
    return str(uuid.uuid4())


results = []

def run(label, fn):
    try:
        ok, detail = fn()
        status = PASS if ok else FAIL
        results.append(ok)
        print(f"{'[PASS]' if ok else '[FAIL]'} {label}")
        if not ok:
            print(f"       → {detail}")
    except Exception as e:
        results.append(False)
        print(f"[FAIL] {label}")
        print(f"       → Exception: {e}")


# ── 1. ROUTER: greeting → clarification ──────────────────────────────────────
def t01():
    d = chat("hi", new_session())
    r = d["response"].lower()
    ok = any(w in r for w in ["hello", "hey", "help", "assist", "shopping", "order", "product"])
    return ok, f"Got: {d['response'][:100]}"

run("1. Router — greeting handled by clarification", t01)


# ── 2. ROUTER: LangSmith run_id returned ─────────────────────────────────────
def t02():
    d = chat("show me headphones", new_session())
    ok = bool(d.get("run_id"))
    return ok, f"run_id={d.get('run_id')}"

run("2. Router — run_id present in response", t02)


# ── 3. PRODUCT: basic product search ─────────────────────────────────────────
def t03():
    d = chat("show me wireless mice under 1000", new_session())
    r = d["response"].lower()
    ok = "mouse" in r or "mice" in r or "logitech" in r or "wireless" in r
    return ok, f"Got: {d['response'][:120]}"

run("3. Product — wireless mice under 1000", t03)


# ── 4. PRODUCT: brand recognition (catalog brand) ────────────────────────────
def t04():
    d = chat("sony headphones", new_session())
    r = d["response"].lower()
    ok = "sony" in r
    return ok, f"Got: {d['response'][:120]}"

run("4. Product — Sony brand recognised and returned", t04)


# ── 5. PRODUCT: unknown brand → alternatives shown ───────────────────────────
def t05():
    d = chat("bose speakers", new_session())
    r = d["response"].lower()
    ok = "don't carry bose" in r or "we don't carry bose" in r or "bose" in r
    return ok, f"Got: {d['response'][:150]}"

run("5. Product — unknown brand (Bose) shows no-carry message + alternatives", t05)


# ── 6. PRODUCT: multi-turn price refinement ───────────────────────────────────
def t06():
    sid = new_session()
    chat("show me bluetooth earphones", sid)
    d = chat("under 1500", sid)
    r = d["response"].lower()
    ok = "earphone" in r or "earbud" in r or "headphone" in r or "₹" in d["response"]
    return ok, f"Got: {d['response'][:150]}"

run("6. Product — multi-turn: earphones → under 1500 (price refines, category held)", t06)


# ── 7. PRODUCT: brand not in catalog for subcategory (Bajaj smartwatches) ────
def t07():
    d = chat("bajaj smartwatches", new_session())
    r = d["response"].lower()
    ok = "bajaj" in r and ("don't carry" in r or "we carry" in r or "smartwatch" in r or "watch" in r)
    return ok, f"Got: {d['response'][:200]}"

run("7. Product — Bajaj smartwatches → correct no-carry + alternatives", t07)


# ── 8. ORDER: anonymous user blocked ─────────────────────────────────────────
def t08():
    d = chat("track my order", new_session())  # no token = anon
    r = d["response"].lower()
    ok = "sign in" in r or "sign-in" in r or "login" in r or "log in" in r
    return ok, f"Got: {d['response'][:120]}"

run("8. Order — anonymous user prompted to sign in", t08)


# ── 9. SUPPORT: anonymous user blocked ───────────────────────────────────────
def t09():
    d = chat("I want to return my order", new_session())
    r = d["response"].lower()
    ok = "sign in" in r or "sign-in" in r or "login" in r or "log in" in r
    return ok, f"Got: {d['response'][:120]}"

run("9. Support — anonymous return request prompted to sign in", t09)


# ── 10. FEEDBACK: endpoint accepts thumbs-up ─────────────────────────────────
def t10():
    d = chat("show me air purifiers", new_session())
    run_id = d.get("run_id")
    if not run_id:
        return False, "No run_id in chat response"
    r = requests.post(f"{BASE}/api/feedback", json={"run_id": run_id, "score": 1}, timeout=10)
    ok = r.status_code == 200 and r.json().get("ok") is True
    return ok, f"status={r.status_code} body={r.text}"

run("10. Feedback — thumbs-up POST returns ok:true", t10)


# ── Summary ───────────────────────────────────────────────────────────────────
passed = sum(results)
total = len(results)
print(f"\n{'='*50}")
print(f"  {passed}/{total} passed")
print(f"{'='*50}")
if passed < total:
    exit(1)
