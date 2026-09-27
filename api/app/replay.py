"""Honest replay over the corpus.

Lookahead control, corrected after measurement (docs/MODELS.md 9.1): `query_timestamp` does NOT filter on
Hindsight API 0.10.1, so we filter ourselves. For each launch we keep only recalled memories whose
`occurred_start` precedes that launch's timestamp. Deterministic and free (recall uses no LLM).

The verdict never comes from an LLM, so the metric is reproducible from the corpus alone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import hindsight
from .config import settings
from .corpus import ground_truth
from .rank import rank, verdict


def _prefix(launch_date: datetime) -> datetime:
    return launch_date.replace(tzinfo=timezone.utc) if launch_date.tzinfo is None else launch_date


def _before(mem: dict[str, Any], cutoff: datetime) -> bool:
    ts = mem.get("occurred_start") or ""
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d < cutoff
    except Exception:  # noqa: BLE001
        return False


async def run_replay(*, max_launches: int | None = None, cache: bool = True) -> dict[str, Any]:
    gt = ground_truth()
    launches = [l for l in gt["launches"] if l["materialised"]]
    launches.sort(key=lambda l: l["date"])
    if max_launches:
        launches = launches[:max_launches]

    rows: list[dict[str, Any]] = []
    for l in launches:
        cutoff = _prefix(datetime.fromisoformat(l["date"] + "T00:00:00"))
        mems = await hindsight.recall(
            f"change on {l['service']} class {l['change_class']} that caused {l['outcome']}",
            budget="mid", max_tokens=1200,
        )
        # our own no-lookahead filter: drop anything dated at or after this launch
        visible = [m for m in mems if _before(m, cutoff)]
        ranked = rank(visible, now=cutoff, service=l["service"], change_class=l["change_class"],
                      min_proof=settings().min_proof)
        v = verdict(ranked, service=l["service"], change_class=l["change_class"])
        rows.append({
            "launch_id": l["launch_id"],
            "date": l["date"],
            "pattern_id": l["pattern_id"],
            "outcome": l["outcome"],
            "materialised": True,
            "flagged_high": v["risk"] == "high",
            "flagged_any": not v["no_precedent"],
            "found_precedent": len(ranked) > 0,
            "cited": ranked[0]["launch_id"] if ranked else None,
            "derivable": l["precedent_derivable"],
            "expected_precedent": l["precedent_launch_id"],
            "precedent_count": len(ranked),
        })

    # epoch buckets
    epochs = []
    for i, start in enumerate(range(0, len(rows), 5)):
        chunk = rows[start:start + 5]
        if not chunk:
            continue
        flagged = [r for r in chunk if r["flagged_high"]]
        materialised = [r for r in chunk if r["materialised"]]
        found = [r for r in chunk if r["found_precedent"]]
        epochs.append({
            "epoch": i + 1,
            "launches": len(chunk),
            "precision": round(len(flagged) / len(flagged), 3) if flagged else None,
            "coverage": round(len(found) / len(materialised), 3) if materialised else None,
            "flagged_high": len(flagged),
        })

    total_materialised = len(rows)
    found = sum(1 for r in rows if r["found_precedent"])
    derivable = sum(1 for r in rows if r["derivable"])
    out = {
        "rows": rows,
        "epochs": epochs,
        "totals": {
            "launches": total_materialised,
            "found_precedent": found,
            "found_coverage": round(found / total_materialised, 3) if total_materialised else 0.0,
            "derivable": derivable,
            "derivable_coverage": round(derivable / total_materialised, 3) if total_materialised else 0.0,
            "gap": derivable - found,
        },
        "method": ("recall (no LLM) + our own occurred_start filter. query_timestamp is a ranking hint and "
                   "does NOT filter on API 0.10.1, so no-lookahead is enforced here in code."),
    }
    if cache:
        try:
            import json, pathlib
            p = pathlib.Path(__file__).resolve().parents[2] / "data"
            p.mkdir(exist_ok=True)
            (p / "replay.json").write_text(json.dumps(out, indent=1))
            out["cached_to"] = str(p / "replay.json")
        except Exception:  # noqa: BLE001
            pass
    return out
