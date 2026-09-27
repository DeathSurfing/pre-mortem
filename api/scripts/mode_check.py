"""Mode routing check against a running server: chat messages vs decisions."""
import json
import subprocess
import sys
import urllib.parse

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"

MSGS = [
    ("chat", "hey, how are you doing today?"),
    ("chat", "what does this tool actually do?"),
    ("chat", "thanks, that helps"),
    ("decision", "Should I give Acme a 30 percent discount to close the renewal this quarter?"),
    ("decision", "We are considering opening an office in Lisbon."),
    # questions about the records: must recall and cite, not answer from general knowledge
    ("query", "what caused the most loss in the year?"),
    ("query", "which decision cost us the most money?"),
    ("query", "what did we decide about the Acme renewal?"),
]


def stream(text: str) -> list[dict]:
    q = urllib.parse.urlencode({"prompt": text})
    out = subprocess.run(
        ["curl", "-sN", "-m", "240", f"{BASE}/api/biz/redflag/stream?{q}"],
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


ok = True
for expected, msg in MSGS:
    ev = stream(msg)
    if not ev:
        print(f"  NO EVENTS for {msg[:50]!r}")
        ok = False
        continue
    kinds = [e["type"] for e in ev if e["type"] not in ("delta", "reasoning")]
    classify = next((e for e in ev if e["type"] == "classify"), {})
    mode = classify.get("mode")
    answer = "".join(e.get("text", "") for e in ev if e["type"] == "delta")
    think = "".join(e.get("text", "") for e in ev if e["type"] == "reasoning")
    has_verdict = any(e["type"] == "verdict" for e in ev)
    has_precedents = any(e["type"] == "precedents" for e in ev)
    cites = any(x in answer for x in ("D-2025", "D-2026", "D-2027"))

    # the contract: chat must be a plain reply, decisions must be reviewed
    if expected == "chat":
        good = mode == "chat" and not has_verdict and not cites
    elif expected == "query":
        # a records question must retrieve the records it answers from, and must not be a verdict
        good = mode == "query" and has_precedents and not has_verdict
    else:
        good = mode == "decision" and has_verdict

    ok = ok and good
    print(f"  [{'OK ' if good else 'BAD'}] want={expected:8} got={str(mode):8} "
          f"verdict={has_verdict!s:5} precedents={has_precedents!s:5} cites={cites!s:5} "
          f"think={len(think):5}ch | {msg[:44]}")

print("\nALL ROUTED CORRECTLY" if ok else "\nROUTING PROBLEM")
sys.exit(0 if ok else 1)
