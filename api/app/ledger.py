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
    """Read the ledger back. recall only, so no LLM cost."""
    # metadata IS preserved on every extracted fact (verified), so this filter is reliable.
    # recall is free, so a slightly larger ask costs nothing.
    flags = await hindsight.recall(
        "pre-mortem tool flag raised on a launch: was it ignored, and did an incident follow",
        types=["world", "experience", "observation"], budget="mid", max_tokens=2000)
    rows = []
    for f in flags:
        meta = f.get("metadata") or {}
        if meta.get("kind") != "flag":
            continue
        rows.append({
            "launch_id": meta.get("launch_id"),
            "service": meta.get("service"),
            "change_class": meta.get("change_class"),
            "ignored": meta.get("ignored") == "true",
            "costed": meta.get("costed") == "true",
            "text": (f.get("text") or "")[:220],
        })
    ignored = [r for r in rows if r["ignored"]]
    costed = [r for r in rows if r["costed"]]
    promoted = sorted({f"{r['change_class']}@{r['service']}" for r in costed})
    return {
        "flags": len(rows),
        "ignored": len(ignored),
        "costed": len(costed),
        "promoted_classes": promoted,
        "rows": rows[:12],
    }


async def promoted_classes() -> set[str]:
    s = await summary()
    return set(s.get("promoted_classes") or [])
