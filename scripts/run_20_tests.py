#!/usr/bin/env python3
"""
20-test regression suite against localhost:8000.
Results written to tat.txt.
"""
import httpx, json, sys, textwrap
from datetime import datetime

BASE = "http://localhost:8000"
HEADERS = {"Content-Type": "application/json", "X-User-ID": "anon-tester"}

PASS = FAIL = 0
lines = []

def chat(msg, session_id=None, user="anon-tester"):
    payload = {"message": msg}
    if session_id:
        payload["session_id"] = session_id
    h = {**HEADERS, "X-User-ID": user}
    r = httpx.post(f"{BASE}/chat", json=payload, headers=h, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d.get("response", ""), d.get("session_id", "")

def check(resp, must_have=(), must_not=(), label=""):
    ok = True
    r = resp.lower()
    for w in must_have:
        if w.lower() not in r:
            ok = False
    for w in must_not:
        if w.lower() in r:
            ok = False
    return ok

def run(num, label, turns, must_have=(), must_not=(), user="anon-tester"):
    global PASS, FAIL
    sid = None
    resp = ""
    try:
        for msg in turns:
            resp, sid = chat(msg, sid, user)
    except Exception as e:
        resp = f"[ERROR] {e}"

    ok = check(resp, must_have, must_not)
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1

    header = f"===== {num:02d}: {label} [{status}] ====="
    print(header)
    wrapped = textwrap.fill(resp, 120) if resp else "(empty)"
    print(wrapped[:600])
    print()
    lines.append(header)
    lines.append(wrapped[:600])
    lines.append("")


# ── 1. wireless mouse under 1000 (single turn) ──────────────────────────────
run(1, "wireless mouse under 1000",
    ["wireless mouse under 1000"],
    must_have=["mouse"],
    must_not=["don't carry", "dont carry"])

# ── 2. wireless mouse → what about Logitech (brand refinement) ──────────────
run(2, "wireless mouse → what about Logitech",
    ["wireless mouse under 1000", "what about Logitech"],
    must_have=["logitech"],
    must_not=["don't carry", "dont carry"])

# ── 3. neckband headphones ───────────────────────────────────────────────────
run(3, "neckband headphones",
    ["neckband headphones"],
    must_have=["neckband"],
    must_not=["don't carry", "dont carry"])

# ── 4. tv ────────────────────────────────────────────────────────────────────
run(4, "tv (browse)",
    ["tv"],
    must_have=["tv"],
    must_not=["don't carry", "dont carry"])

# ── 5. smart tv under 15000 ──────────────────────────────────────────────────
run(5, "smart tv under 15000",
    ["smart tv under 15000"],
    must_have=["tv"],
    must_not=["don't carry", "dont carry"])

# ── 6. smart tv → what about Samsung (brand refinement) ─────────────────────
run(6, "smart tv → what about Samsung",
    ["smart tv under 15000", "what about Samsung"],
    must_have=["samsung"],
    must_not=["don't carry", "dont carry"])

# ── 7. air fryer ─────────────────────────────────────────────────────────────
run(7, "air fryer",
    ["air fryer"],
    must_have=["air fryer"],
    must_not=["don't carry", "dont carry"])

# ── 8. air fryer → what about Philips ───────────────────────────────────────
run(8, "air fryer → what about Philips",
    ["air fryer", "what about Philips"],
    must_have=["philips"],
    must_not=["don't carry", "dont carry"])

# ── 9. mixer grinder under 2000 ──────────────────────────────────────────────
run(9, "mixer grinder under 2000",
    ["mixer grinder under 2000"],
    must_have=["mixer"],
    must_not=["don't carry", "dont carry"])

# ── 10. mixer grinder → what about Bajaj ────────────────────────────────────
run(10, "mixer grinder → what about Bajaj",
    ["mixer grinder under 2000", "what about Bajaj"],
    must_have=["bajaj"],
    must_not=["don't carry", "dont carry"])

# ── 11. mixer grinder → under 1500 (price refinement) ───────────────────────
run(11, "mixer grinder → under 1500 (price refinement)",
    ["mixer grinder under 2000", "under 1500"],
    must_have=["mixer"],
    must_not=["what are you looking for", "looking for today", "don't carry"])

# ── 12. 4K monitor (spec keyword — shows monitors or polite redirect) ────────
run(12, "4K monitor (spec filter or redirect)",
    ["4k monitor"],
    must_have=["monitor"],
    must_not=[])

# ── 13. laptop bag 15.6 inch ─────────────────────────────────────────────────
run(13, "laptop bag 15.6 inch",
    ["laptop bag 15.6 inch"],
    must_have=["bag"],
    must_not=[])

# ── 14. USB hub with ethernet (spec keyword — shows hubs or polite redirect) ─
run(14, "USB hub with ethernet (spec filter or redirect)",
    ["usb hub with ethernet"],
    must_have=["hub"],
    must_not=[])

# ── 15. TWS earbuds under 2000 ───────────────────────────────────────────────
run(15, "TWS earbuds under 2000",
    ["tws earbuds under 2000"],
    must_have=["earbud"],
    must_not=["don't carry", "dont carry"])

# ── 16. room heater under 2000 ───────────────────────────────────────────────
run(16, "room heater under 2000",
    ["room heater under 2000"],
    must_have=["heater"],
    must_not=["don't carry", "dont carry"])

# ── 17. ceiling fan under 5000 ───────────────────────────────────────────────
run(17, "ceiling fan under 5000",
    ["ceiling fan under 5000"],
    must_have=["fan"],
    must_not=["don't carry", "dont carry"])

# ── 18. calculator ───────────────────────────────────────────────────────────
run(18, "calculator (in catalog as 'calculators')",
    ["calculator"],
    must_have=["casio", "calculator"],
    must_not=["don't carry", "dont carry"])

# ── 19. smartwatches under 3000 ──────────────────────────────────────────────
run(19, "smartwatches under 3000",
    ["smartwatches under 3000"],
    must_have=["watch"],
    must_not=["don't carry", "dont carry"])

# ── 20. smartwatches → what about Fire-Boltt ─────────────────────────────────
run(20, "smartwatches → what about Fire-Boltt",
    ["smartwatches under 3000", "what about Fire-Boltt"],
    must_have=["fire-boltt"],
    must_not=["don't carry", "dont carry"])

# ── Summary ──────────────────────────────────────────────────────────────────
summary = f"\nResults: {PASS}/20 passed ({FAIL} failed)  — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
print(summary)
lines.append(summary)

with open("tat.txt", "w") as f:
    f.write("\n".join(lines) + "\n")

print("Written to tat.txt")
sys.exit(0 if FAIL == 0 else 1)
