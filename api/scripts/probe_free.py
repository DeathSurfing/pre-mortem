"""Free-only probe (no LLM calls): bank config shape, directives API, query_timestamp semantics."""
import asyncio, inspect, json, os, sys

from hindsight_client import Hindsight

BANK = "premortem-probe"
c = Hindsight(base_url=os.environ.get("HS_URL", "https://api.hindsight.vectorize.io"),
              api_key=os.environ["HS_KEY"], timeout=120, max_attempts=1)

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def call(fn, *a, **k):
    r = fn(*a, **k)
    return _LOOP.run_until_complete(r) if inspect.iscoroutine(r) else r


def dump(label, obj, limit=900):
    print(f"\n== {label} ==")
    if isinstance(obj, dict):
        for k, v in obj.items():
            print(f"   {k}: {str(v)[:200]}")
    else:
        print("   ", str(obj)[:limit])
    sys.stdout.flush()


print("== namespaces on client ==")
print("   ", [n for n in dir(c) if not n.startswith("_")][:40])

dump("bank config (nested)", call(c.banks.get_bank_config, BANK))

print("\n== config sub-keys ==")
try:
    cfg = call(c.banks.get_bank_config, BANK)
    d = cfg if isinstance(cfg, dict) else cfg.to_dict()
    sub = d.get("config") or {}
    for k in sorted(sub.keys()):
        print(f"   {k}: {str(sub[k])[:120]}")
except Exception as e:
    print("   ERR", type(e).__name__, str(e)[:200])

print("\n== directives api ==")
try:
    api = c.directives
    print("   methods:", [n for n in dir(api) if not n.startswith("_") and not n.endswith("http_info")][:12])
    print("   signature list:", inspect.signature(api.list))
except Exception as e:
    print("   ERR", type(e).__name__, str(e)[:250])

print("\n== query_timestamp semantics (does it hard-filter by event time?) ==")
for label, qts in [
    ("no timestamp", None),
    ("as of 2026-03-13 (day before the root fact)", "2026-03-13T00:00:00Z"),
    ("as of 2024-01-01 (before everything)", "2024-01-01T00:00:00Z"),
]:
    try:
        res = c.recall(bank_id=BANK, query="connection pool change payments latency", budget="low",
                       max_tokens=600, query_timestamp=qts, include_chunks=False)
        occ = sorted({(m.occurred_start or "")[:10] for m in res.results})
        print(f"   {label:44} n={len(res.results)} occurred={occ}")
    except Exception as e:
        print(f"   {label:44} ERR {type(e).__name__} {str(e)[:120]}")
    sys.stdout.flush()

print("\n== recall tags filter (can we scope by metadata/tag?) ==")
try:
    res = c.recall(bank_id=BANK, query="pool change", budget="low", max_tokens=400)
    print("   plain recall n=", len(res.results))
    print("   tags on results:", {tuple(m.tags or []) for m in res.results})
    print("   document_id present:", {m.document_id for m in res.results})
except Exception as e:
    print("   ERR", type(e).__name__, str(e)[:200])

print("\n== list memories / documents namespaces ==")
for ns in ("memories", "documents", "entities", "mental_models", "tags", "operations"):
    obj = getattr(c, ns, None)
    print(f"   {ns}: {'MISSING' if obj is None else 'ok'}")

print("\nDONE (no LLM calls made)")
