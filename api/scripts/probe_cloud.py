"""Frugal Hindsight Cloud probe. LLM calls used: 1 (test_bank_llm) + 1 retain extraction.

Credit discipline: recall() is retrieval-only (no LLM) per Hindsight docs; retain() and reflect() cost LLM.
So this probe does exactly one retain and one recall, and no reflect.
"""
import asyncio
import inspect
import json
import os
import sys
from datetime import datetime, timedelta

from hindsight_client import Hindsight

BANK = "premortem-probe"

KEY = os.environ["HS_KEY"]
URL = os.environ.get("HS_URL", "https://api.hindsight.vectorize.io")

# max_attempts=1: never silently retry a paid call
c = Hindsight(base_url=URL, api_key=KEY, timeout=120, max_attempts=1)  # never retry a paid call


# ONE persistent event loop for the whole process. The client's own sync wrapper calls
# asyncio.get_event_loop(), so asyncio.run() here would close the loop it later depends on.
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def call(fn, *a, **k):
    """Bank-namespace methods are async; core ops are sync. Run everything on one loop."""
    r = fn(*a, **k)
    if inspect.iscoroutine(r):
        return _LOOP.run_until_complete(r)
    return r


def step(label):
    print(f"\n== {label} ==")
    sys.stdout.flush()


step("1. auth / list banks (free)")
try:
    banks = call(c.banks.list_banks)
    print("  ok:", str(banks)[:200])
except Exception as e:
    print("  ERR", type(e).__name__, str(e)[:300])
    sys.exit(1)

step("2. get_version")
try:
    v = call(c.get_version)
    print("  api_version:", v.api_version)
    print("  features:", {k: getattr(v.features, k, None) for k in dir(v.features) if not k.startswith("_")} if getattr(v, "features", None) else None)
except Exception as e:
    print("  ERR", type(e).__name__, str(e)[:300])

step("3. bank config (mission / directives / disposition)")
try:
    from hindsight_client_api.models.create_bank_request import CreateBankRequest
    from hindsight_client_api.models.disposition_traits import DispositionTraits
    req = CreateBankRequest(
        name="Pre-mortem probe",
        mission="I am a change-risk pre-mortem agent. I argue from precedent and cite launch IDs.",
        disposition=DispositionTraits(skepticism=4, literalism=5, empathy=2),
        enable_observations=True,
        retain_custom_instructions="Extract the change, the symptom, the outcome, and the fix as separate facts.",
    )
    call(c.banks.create_or_update_bank, BANK, req)
    cfg = call(c.banks.get_bank_config, BANK)
    print("  config type:", type(cfg).__name__)
    d = cfg if isinstance(cfg, dict) else cfg.to_dict()
    print("  mission:", (d.get("mission") or "")[:70])
    print("  disposition:", d.get("disposition"))
    print("  enable_observations:", d.get("enable_observations"))
    print("  keys:", sorted(d.keys())[:22])
except Exception as e:
    print("  ERR", type(e).__name__, str(e)[:400])

step("4. test_bank_llm (1 tiny LLM call)")
try:
    print("  ", str(call(c.banks.test_bank_llm, BANK))[:300])
except Exception as e:
    print("  ERR", type(e).__name__, str(e)[:300])

step("5. retain ONE launch (1 extraction call)")
ts = datetime(2026, 3, 14, 9, 30)
doc = (
    "Launch L-2026-0412 | payments-service | config-only\n"
    "Change: reduced connection pool size 40 -> 20, no other parameter touched.\n"
    "Diff: application.yml hikari.pool-size 40 -> 20\n"
    "Symptom: p99 latency 210ms -> 1.9s. HikariPool-1 Connection is not available, "
    "request timed out after 30000ms (total=20, active=20, idle=0, waiting=83).\n"
    "Outcome: incident, sev2, 46 minutes.\n"
    "Fix applied: raised max_overflow to 20 and set pool_pre_ping=true; the pool was sized "
    "without headroom for the p99 burst path.\n"
    "Note: the identical pool change in L-2025-1101 shipped clean because max_overflow was raised in the same commit."
)
try:
    r = c.retain(
        bank_id=BANK,
        content=doc,
        context="post-deploy change record",
        timestamp=ts,
        document_id="L-2026-0412",
        metadata={
            "launch_id": "L-2026-0412",
            "service": "payments-service",
            "change_class": "config-only",
            "pattern_id": "P1",
            "outcome": "incident",
        },
    )
    print("  retain ok:", str(r)[:250])
except Exception as e:
    print("  ERR", type(e).__name__, str(e)[:600])

step("6. stats (free)")
try:
    s = call(c.banks.get_agent_stats, BANK)
    d = s if isinstance(s, dict) else s.to_dict()
    for k in ("total_nodes", "total_documents", "nodes_by_fact_type", "total_observations",
              "pending_consolidation", "last_consolidated_at"):
        print(f"   {k}: {d.get(k)}")
except Exception as e:
    print("  ERR", type(e).__name__, str(e)[:300])

step("7. recover_consolidation (free, forces observations)")
try:
    print("  ", str(call(c.banks.recover_consolidation, BANK))[:250])
except Exception as e:
    print("  ERR", type(e).__name__, str(e)[:250])

step("8. recall (NO LLM - retrieval only)")
try:
    res = c.recall(
        bank_id=BANK,
        query="connection pool change on payments-service caused a latency spike",
        types=["world", "experience", "observation"],
        budget="low",
        max_tokens=900,
        include_chunks=True,
        include_entities=True,
    )
    print("  results:", len(res.results))
    for m in res.results:
        print(f"   type={m.type} id={m.id[:12]}... ")
        print(f"     text: {m.text[:160]!r}")
        print(f"     meta: {m.metadata}")
        print(f"     occurred_start: {m.occurred_start}")
    if res.chunks:
        for mid, ch in list(res.chunks.items())[:2]:
            print(f"   chunk[{mid[:10]}]: {str(getattr(ch,'text',''))[:110]!r}")
except Exception as e:
    print("  ERR", type(e).__name__, str(e)[:500])

step("9. recall with query_timestamp (no-lookahead check)")
try:
    before = (ts - timedelta(days=1)).isoformat()
    res = c.recall(bank_id=BANK, query="pool change payments", query_timestamp=before,
                   budget="low", max_tokens=600)
    print(f"  as of {before}: {len(res.results)} results")
    for m in res.results:
        print(f"     {m.text[:90]!r}")
except Exception as e:
    print("  ERR", type(e).__name__, str(e)[:300])

step("10. memories timeseries by occurred_start (free)")
import inspect as _i
print("  get_memories_timeseries sig:", _i.signature(c.banks.get_memories_timeseries))

print("\nDONE")
