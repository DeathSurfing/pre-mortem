"""The ignored-warning ledger.

Retains each flag the tool raised, whether it was ignored, and whether ignoring it cost an incident.
Then hands back the promoted `change_class@service` keys so `rank()` can lead with that class.

Cost: 4 small retains at seed time. No LLM calls afterwards (recall is free).
"""
from __future__ import annotations

from typing import Any

from . import hindsight
from .config import settings
from .corpus import LEDGER_SEED, corpus


def _launch_index() -> dict[int, Any]:
    return {l.idx: l for l in corpus()}


async def seed_ledger() -> dict[str, Any]:
    idx = _launch_index()
    items = []
    for launch_idx, flag, ignored, costed in LEDGER_SEED:
        l = idx.get(launch_idx)
        if l is None:
            continue
        items.append({
            "content": (
                f"FLAG raised by the pre-mortem tool on {l.launch_id} ({l.date.date().isoformat()}): {flag}. "
                f"The engineer {'IGNORED' if ignored else 'ACTIONED'} this flag. "
                f"{'The ignored flag was followed by an incident.' if costed else 'No incident followed.'}"
            ),
            "context": "pre-mortem flag ledger",
            "timestamp": l.date.isoformat(),
            # deterministic id, so re-seeding replaces rather than accumulates
            "document_id": f"FLAG-{l.launch_id}",
            "metadata": {
                "kind": "flag",
                "launch_id": l.launch_id,
                "service": l.service,
                "change_class": l.change_class,
                "ignored": "true" if ignored else "false",
                "costed": "true" if costed else "false",
            },
        })
    if not items:
        return {"seeded": 0}
    r = await hindsight.client().aretain_batch(bank_id=settings().bank_id, items=items, retain_async=False)
    return {"seeded": len(items), "raw": str(r)[:150]}


async def summary() -> dict[str, Any]:
    """Read the ledger back. recall only, so no LLM cost.

    One flag = one row. Hindsight extracts several facts per flag document and its consolidation adds
    observations derived from those facts, so the raw result set repeats each flag many times (measured:
    4 flags came back as 20 world facts). Dedupe by launch_id, keep only `world` facts, because an
    observation about a flag is a summary of it, not a second flag.
    """
    flags = await hindsight.recall(
        "pre-mortem tool flag raised on a launch: was it ignored, and did an incident follow",
        types=["world"], budget="mid", max_tokens=3000)
    by_launch: dict[str, dict[str, Any]] = {}
    for f in flags:
        meta = f.get("metadata") or {}
        if meta.get("kind") != "flag":
            continue
        lid = meta.get("launch_id")
        if not lid or lid in by_launch:
            continue
        by_launch[lid] = {
            "launch_id": lid,
            "service": meta.get("service"),
            "change_class": meta.get("change_class"),
            "ignored": meta.get("ignored") == "true",
            "costed": meta.get("costed") == "true",
            "text": (f.get("text") or "")[:220],
        }
    rows = sorted(by_launch.values(), key=lambda r: r["launch_id"] or "")
    ignored = [r for r in rows if r["ignored"]]
    costed = [r for r in rows if r["costed"]]
    promoted = sorted({f"{r['change_class']}@{r['service']}" for r in costed})
    return {
        "flags": len(rows),
        "ignored": len(ignored),
        "costed": len(costed),
        "promoted_classes": promoted,
        "rows": rows,
        "note": "one row per flag; source facts are deduped by launch_id",
    }


async def promoted_classes() -> set[str]:
    s = await summary()
    return set(s.get("promoted_classes") or [])
