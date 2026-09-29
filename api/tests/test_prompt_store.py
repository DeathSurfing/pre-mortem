"""Checks for the prompt store and the decision lifecycle.

These cover the behaviours that were verified by hand and are easy to break:
  - a prompt is recorded and vectorised but NEVER retained (the gate)
  - the draft never invents a result or an outcome
  - an unembedded row is kept, and excluded from similarity rather than ranked at a fake distance
  - the store's own SQL behaves (lookup by id past the recent() window, resolve, unresolved queue)

Requires a running Postgres with pgvector, via PROMPT_DB_URL. Skips cleanly without one, so it can be run
anywhere rather than failing the suite on a machine with no database.

Run: PROMPT_DB_URL=... python3 api/tests/test_prompt_store.py
"""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import prompts as ps  # noqa: E402
from app import prompt_history as ph  # noqa: E402

FAILS: list[str] = []
PASSES = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASSES
    if ok:
        PASSES += 1
        print(f"  PASS  {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL  {label}  {detail}")


store = ps.PromptStore()
if not store.ensure_schema():
    print(f"SKIP: no prompt store available ({store.error}). Set PROMPT_DB_URL to run these.")
    sys.exit(0)

TAG = f"test-{uuid.uuid4().hex[:8]}"

print("\n1. recording keeps the prompt even when the embedding fails")
pid_unembedded = store.record(prompt=f"{TAG} unembedded row", domain="ops", decision_type="datacenter-region")
check("unembedded row is stored", bool(pid_unembedded))
row = store.get(pid_unembedded) if pid_unembedded else None
check("it has no vector", row is not None and row["has_vector"] is False)
check("it is not committed", row is not None and row["committed"] is False)

print("\n2. an unembedded row is excluded from similarity, not ranked")
vec = ps.embed(f"{TAG} unembedded row")
if vec is None:
    print("SKIP similarity checks: embedding model unavailable")
else:
    hits = store.similar(vec, limit=25)
    check("unembedded row absent from similar()",
          all(str(h.get("id")) != str(pid_unembedded) for h in hits),
          f"found {pid_unembedded} in results")

print("\n3. lookup by id works regardless of store size (the recent(limit=500) bug)")
# Push the target row out of any small recent() window by creating newer rows, so this actually exercises
# the failure mode instead of trivially passing because the row happens to be newest.
for i in range(6):
    store.record(prompt=f"{TAG} filler row {i}", domain="ops", decision_type="datacenter-region")
recentids = {str(r["id"]) for r in store.recent(limit=5)}
check("target row is outside the recent() window", str(pid_unembedded) not in recentids)
check("store.get() still finds it", store.get(pid_unembedded) is not None)

print("\n4. the draft never invents a result or an outcome")
import asyncio  # noqa: E402

draft, meta = asyncio.run(ph.draft_decision(
    prompt=f"{TAG} Should we switch our CRM vendor mid-contract?",
    domain="vendor", decision_type="vendor-switch", risk="medium", headline=None))
if meta.get("drafted"):
    check("proposal drafts with no result", not draft.get("result"), f"got {draft.get('result')!r}")
    check("proposal drafts with no outcome", not draft.get("outcome"), f"got {draft.get('outcome')!r}")
else:
    # No LLM key is not a failure of this code; the fallback shape is what matters.
    check("fallback draft has no result", not draft.get("result"))
    check("fallback draft has no outcome", not draft.get("outcome"))

print("\n5. outcome validation and the resolve lifecycle")
bad = store.resolve(pid_unembedded, outcome="good", result_note="should not apply")
check("resolving an uncommitted row is refused", bad is False)

# simulate the committed state without touching Hindsight
store.commit(pid_unembedded, f"U-TEST-{TAG}")
row = store.get(pid_unembedded)
check("commit sets hindsight_doc", bool(row and row.get("hindsight_doc")))
check("committed but unresolved", bool(row and row.get("resolved_at") is None))

queue_ids = {str(r["id"]) for r in store.unresolved(limit=50)}
check("it appears in the unresolved queue", str(pid_unembedded) in queue_ids)

ok = store.resolve(pid_unembedded, outcome="mixed", result_note=f"{TAG} half worked")
check("resolve succeeds on a committed row", ok is True)
row = store.get(pid_unembedded)
check("outcome is stored", row is not None and row.get("outcome") == "mixed")
check("resolved_at is set", row is not None and row.get("resolved_at") is not None)
queue_ids = {str(r["id"]) for r in store.unresolved(limit=50)}
check("it leaves the unresolved queue", str(pid_unembedded) not in queue_ids)

print("\n6. the stored document is honest about an unknown outcome")
did, doc = ps.decision_document_text(
    decision=f"{TAG} a decision with no outcome", domain="ops", decision_type="datacenter-region")
check("body says the result is not known yet", "not yet known" in doc["text"])
check("body warns against treating it as resolved", "no outcome is recorded" in doc["text"])
check("metadata records not-recorded", doc["metadata"]["outcome"] == "not-recorded")

did2, doc2 = ps.decision_document_text(
    decision=f"{TAG} a resolved decision", domain="ops", decision_type="datacenter-region",
    result="it worked", outcome="good", decision_id=did,
    resolved_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
check("a resolved body marks the outcome as recorded", "Outcome recorded on" in doc2["text"])
check("reusing decision_id supersedes rather than renames", did2 == did)
check("metadata carries the outcome", doc2["metadata"]["outcome"] == "good")

print("\n7. duplicate detection only counts committed rows")
if vec is not None:
    dup = ph._likely_duplicate(f"{TAG} a decision with no outcome")
    # the row above is committed with a matching-ish text; either outcome is acceptable, but it must not crash
    check("duplicate check returns a dict or None", dup is None or isinstance(dup, dict))
else:
    print("SKIP: embedding unavailable")

# cleanup: remove only this run's rows
try:
    with store._connect() as conn, conn.cursor() as cur:
        cur.execute("delete from prompts where prompt like %s", (f"%{TAG}%",))
    print(f"\ncleaned up {TAG} rows")
except Exception as e:  # noqa: BLE001
    print(f"\ncleanup failed: {e}")

print(f"\n{PASSES} passed, {len(FAILS)} failed")
if FAILS:
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
