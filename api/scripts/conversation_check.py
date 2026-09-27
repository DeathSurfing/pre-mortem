"""Conversation routing check: opening question reviewed, follow-ups conversational with context.

Run against a live server: python3 scripts/conversation_check.py [base_url]
"""
import json
import subprocess
import sys

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010").rstrip("/")
URL = f"{BASE}/api/biz/redflag/stream"

FIRST = "Should I give Acme a 30 percent discount to close the renewal this quarter?"
FOLLOWUPS = [
    "What if we cap the discount at 15 percent instead, with a one year term?",
    "which of those decisions was the closest to what I am proposing?",
    "and what would you want to see before agreeing?",
]


def call(payload: dict) -> list[dict]:
    out = subprocess.run(
        ["curl", "-sN", "-m", "240", "-X", "POST", URL,
         "-H", "content-type: application/json", "-d", json.dumps(payload)],
        capture_output=True, text=True, timeout=300,
    ).stdout
    events = []
    for line in out.splitlines():
        if line.startswith("data:"):
            try:
                events.append(json.loads(line[5:].strip()))
            except json.JSONDecodeError:
                pass
    return events


def kinds(ev):
    return {e["type"] for e in ev}


def answer(ev):
    return "".join(e.get("text", "") for e in ev if e["type"] == "delta")


ok = True

# ---- turn 1: an opening question must still be reviewed in full
ev1 = call({"prompt": FIRST})
first_mode = next((e.get("mode") for e in ev1 if e["type"] == "classify"), None)
t1_ok = first_mode == "decision" and "verdict" in kinds(ev1) and "precedents" in kinds(ev1)
ok = ok and t1_ok
print(f"[{'OK ' if t1_ok else 'BAD'}] opening question reviewed   mode={first_mode}")
first_answer = answer(ev1)

# ---- follow-ups: must be conversation, must not re-issue a review, must know the context
history = [
    {"role": "user", "content": FIRST},
    {"role": "assistant", "content": first_answer[:2500]},
]
for q in FOLLOWUPS:
    ev = call({"prompt": q, "history": history})
    mode = next((e.get("mode") for e in ev if e["type"] == "classify"), None)
    is_fu = next((e.get("follow_up") for e in ev if e["type"] == "classify"), None)
    # a follow-up must not carry the decision-path events
    clean = "verdict" not in kinds(ev) and "precedents" not in kinds(ev)
    good = mode == "chat" and is_fu is True and clean
    ok = ok and good
    txt = answer(ev)
    print(f"[{'OK ' if good else 'BAD'}] follow-up                mode={mode} follow_up={is_fu} "
          f"re_reviewed={not clean} | {q[:44]}")
    history += [{"role": "user", "content": q}, {"role": "assistant", "content": txt[:2000]}]

print()
print("ALL CORRECT" if ok else "ROUTING PROBLEM")
sys.exit(0 if ok else 1)
