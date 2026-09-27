"""Which mechanism actually enforces no-lookahead? Candidate: recall_tags / tags filter.

Also settles: directives API, documents listing (for deleting old docs), and whether
tags must be supplied at retain time to be filterable.
"""
import asyncio, inspect, os, sys
from hindsight_client import Hindsight

BANK = "premortem-probe"
c = Hindsight(base_url=os.environ.get("HS_URL", "https://api.hindsight.vectorize.io"),
              api_key=os.environ["HS_KEY"], timeout=120, max_attempts=1)
LOOP = asyncio.new_event_loop(); asyncio.set_event_loop(LOOP)
run = lambda r: LOOP.run_until_complete(r) if inspect.iscoroutine(r) else r


def show(label, fn):
    print(f"\n== {label} ==")
    try:
        r = run(fn())
        print("   ", str(r)[:400])
    except Exception as e:
        print("   ERR", type(e).__name__, str(e)[:250])
    sys.stdout.flush()


print("recall signature (tags params):")
sig = inspect.signature(c.recall)
for n in ("tags", "tags_match", "tag_groups", "query_timestamp", "min_scores", "temporal_window"):
    if n in sig.parameters:
        print(f"   {n}: {sig.parameters[n].default!r}")

show("directives.list_?()", lambda: c.directives.list_directives(BANK))
show("documents.list", lambda: c.documents.list_documents(BANK, limit=5))
show("documents.delete old doc", lambda: c.documents.delete_document(BANK, "L-2025-1101")
     if hasattr(c.documents, "delete_document") else "no delete_document")

print("\n== documents methods ==")
print("   ", [n for n in dir(c.documents) if not n.startswith("_") and "http_info" not in n][:14])
print("\n== entities methods ==")
print("   ", [n for n in dir(c.entities) if not n.startswith("_") and "http_info" not in n][:14])
print("\n== mental_models methods ==")
print("   ", [n for n in dir(c.mental_models) if not n.startswith("_") and "http_info" not in n][:14])

print("\n== can tags filter recall? (nothing tagged yet -> expect n=0) ==")
show("recall tags=['pattern:P1']", lambda: c.recall(bank_id=BANK, query="pool change", budget="low",
                                                    max_tokens=300, tags=["pattern:P1"]))
print("\n== tag_groups form ==")
show("recall tag_groups", lambda: c.recall(bank_id=BANK, query="pool change", budget="low", max_tokens=300,
                                           tag_groups=[{"tags": ["pattern:P1"], "match": "any"}]))
print("\n== min_scores ==")
show("recall min_scores", lambda: c.recall(bank_id=BANK, query="pool change", budget="low", max_tokens=300,
                                            min_scores={"semantic": 0.9, "keyword": 0.9}))
print("\ndone (free)")
