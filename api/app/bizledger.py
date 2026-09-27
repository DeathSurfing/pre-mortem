"""Ignored-warning ledger for business decisions.

Retains each warning the red-flagger raised, whether the person went ahead anyway, and whether that cost
anything. Then hands back the promoted `domain@decision_type` keys so `rank()` leads with the classes that
have burned this company before.

Hindsight extracts several facts per flag document and consolidation adds observations on top, so reads
dedupe by decision id. Verified: 5 flags came back as 20 facts before dedupe.
"""
from __future__ import annotations

from typing import Any

from . import bizcorpus, hindsight
from .config import settings


def _index() -> dict[int, Any]:
    return {d.idx: d for d in bizcorpus.corpus()}


async def seed_ledger(bank_id: str | None = None) -> dict[str, Any]:
    idx = _index()
    items = []
    for i, warning, ignored, costed in bizcorpus.LEDGER_SEED:
        d = idx.get(i)
        if d is None:
            continue
        items.append({
            "content": (
                f"WARNING raised by the decision reviewer on {d.decision_id} ({d.date.date().isoformat()}): "
                f"{warning}. The decision owner {'IGNORED' if ignored else 'ACTIONED'} this warning. "
                f"{'Something went wrong afterwards, consistent with the warning.' if costed else 'Nothing material followed.'}"
            ),
            "context": "decision warning ledger",
            "timestamp": d.date.isoformat(),
            # deterministic id so re-seeding replaces rather than accumulates
            "document_id": f"WARN-{d.decision_id}",
            "metadata": {
                "kind": "warning",
                "decision_id": d.decision_id,
                "domain": d.domain,
                "decision_type": d.decision_type,
                "ignored": "true" if ignored else "false",
                "costed": "true" if costed else "false",
            },
        })
    if not items:
        return {"seeded": 0}
    r = await hindsight.client().aretain_batch(bank_id=bank_id or settings().biz_bank_id,
                                              items=items, retain_async=False)
    return {"seeded": len(items), "raw": str(r)[:150]}


async def summary(bank_id: str | None = None) -> dict[str, Any]:
    """Read the ledger back. recall only, so no LLM cost. One warning = one row."""
    rows_raw = await hindsight.recall(
        "warnings the decision reviewer raised: was the warning ignored, and did anything go wrong",
        types=["world"], budget="mid", max_tokens=3000, bank_id=bank_id or settings().biz_bank_id)
    by_id: dict[str, dict[str, Any]] = {}
    for f in rows_raw:
        meta = f.get("metadata") or {}
        if meta.get("kind") != "warning":
            continue
        did = meta.get("decision_id")
        if not did or did in by_id:
            continue
        by_id[did] = {
            "decision_id": did,
            "domain": meta.get("domain"),
            "decision_type": meta.get("decision_type"),
            "ignored": meta.get("ignored") == "true",
            "costed": meta.get("costed") == "true",
            "text": (f.get("text") or "")[:240],
        }
    rows = sorted(by_id.values(), key=lambda r: r["decision_id"] or "")
    ignored = [r for r in rows if r["ignored"]]
    costed = [r for r in rows if r["costed"]]
    promoted = sorted({f"{r['domain']}@{r['decision_type']}" for r in costed})
    return {
        "flags": len(rows),
        "ignored": len(ignored),
        "costed": len(costed),
        "promoted_classes": promoted,
        "rows": rows,
        "note": "one row per warning; source facts deduped by decision id",
    }


async def promoted_classes(bank_id: str | None = None) -> set[str]:
    s = await summary(bank_id)
    return set(s.get("promoted_classes") or [])
