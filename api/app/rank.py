"""Deterministic ranking + the ledger of ignored warnings.

The verdict is produced here, never by an LLM. The LLM only writes the flip sentence.
Every score component is named so the UI can show the arithmetic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

TREND_PENALTY = {"weakening": -2.0, "stale": -3.0, "new": 0.0, "stable": 0.0, "strengthening": 1.0}
LEDGER_BOOST = 3.0


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        s = str(ts).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def recency_weight(occurred_start: Any, now: datetime) -> float:
    """1.0 for fresh, decaying to 0.2 across ~14 months. Never negative."""
    d = _parse(occurred_start)
    if d is None:
        return 0.5
    days = max(0.0, (now - d).days)
    return max(0.2, 1.0 - days / 430.0)


def proof_count(mem: dict[str, Any]) -> int:
    """Proof of a precedent = how many other launches share its pattern, surfaced by Hindsight.

    We take it from the memory's own metadata/type rather than inventing a number:
    observations carry Hindsight's own consolidated proof; world facts count as 1.
    """
    if (mem.get("type") or "") == "observation":
        return int(mem.get("proof_count") or 2)
    return 1


def score(mem: dict[str, Any], now: datetime, promoted: set[str] | None = None) -> dict[str, float]:
    meta = mem.get("metadata") or {}
    proof = proof_count(mem)
    rec = recency_weight(mem.get("occurred_start"), now)
    trend = (mem.get("trend") or "stable").lower()
    trend_pen = TREND_PENALTY.get(trend, 0.0)
    key = f"{meta.get('change_class')}@{meta.get('service')}"
    led = LEDGER_BOOST if promoted and key in promoted else 0.0
    total = proof * 2.0 + rec + trend_pen + led
    return {
        "proof": float(proof),
        "recency": round(rec, 3),
        "trend_penalty": trend_pen,
        "ledger_boost": led,
        "total": round(total, 3),
    }


def rank(memories: list[dict[str, Any]], *, now: datetime | None = None,
         promoted: set[str] | None = None, service: str | None = None,
         change_class: str | None = None, min_proof: int = 1) -> list[dict[str, Any]]:
    """Rank precedents. Deterministic: same input, same order, no model involved.

    Ties break on launch_id so the order is stable across runs.
    """
    now = now or datetime.now(timezone.utc)
    out = []
    for m in memories:
        if not (m.get("metadata") or {}).get("launch_id"):
            continue  # unattributable memory: cannot be cited as a precedent
        meta = m.get("metadata") or {}
        # STRICT: a precedent must carry the same service AND change class. A memory with no
        # metadata cannot be attributed to a service, so it is not a precedent (tier 1).
        # When service/change_class are None the caller asked for an unfiltered view (rank debug).
        if service is not None and meta.get("service") != service:
            continue
        if change_class is not None and meta.get("change_class") != change_class:
            continue
        if proof_count(m) < min_proof:
            continue
        sc = score(m, now, promoted)
        out.append({
            "launch_id": meta.get("launch_id") or m.get("document_id"),
            "date": (m.get("occurred_start") or "")[:10],
            "service": meta.get("service"),
            "change_class": meta.get("change_class"),
            "outcome": meta.get("outcome"),
            "pattern_id": meta.get("pattern_id"),
            "is_mirror": meta.get("is_mirror") == "true",
            "proof_count": int(sc["proof"]),
            "trend": (m.get("trend") or "stable"),
            "memory_id": m.get("id"),
            "memory_type": m.get("type"),
            "source_chunk": m.get("chunk"),
            "text": m.get("text"),
            "score": sc,
        })
    # Hindsight extracts several facts per launch, so the same launch_id appears repeatedly.
    # One launch = one precedent: keep its highest-scoring fact and remember how many facts it had.
    best: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for r in out:
        lid = r["launch_id"]
        counts[lid] = counts.get(lid, 0) + 1
        cur = best.get(lid)
        if cur is None or r["score"]["total"] > cur["score"]["total"]:
            best[lid] = r
    deduped = []
    for lid, r in best.items():
        r["fact_count"] = counts[lid]
        # the flip detail usually lives in the fact that mentions the differing parameter, which is
        # not always the highest-scoring one. Keep every fact's text so the LLM can see them all.
        r["all_texts"] = [x.get("text") for x in out if x["launch_id"] == lid and x.get("text")]
        deduped.append(r)

    # ordering: materialised outcomes first (a pre-mortem leads with what broke), then score.
    def sort_key(r: dict):
        broke = 0 if (r.get("outcome") in ("incident", "degraded") and not r.get("is_mirror")) else 1
        return (broke, -r["score"]["total"], r["launch_id"] or "")

    deduped.sort(key=sort_key)
    return deduped


def verdict(precedents: list[dict[str, Any]], *, service: str | None, change_class: str | None) -> dict[str, Any]:
    """Risk comes from precedent outcomes, not from the model."""
    if not precedents:
        return {"risk": "unknown", "confidence": 0.0, "no_precedent": True, "rules": "no precedent clears MIN_PROOF"}
    conflicting = [p for p in precedents if not p.get("is_mirror") and p.get("outcome") in ("incident", "degraded")]
    mirrors = [p for p in precedents if p.get("is_mirror")]
    if conflicting and mirrors:
        risk = "medium"
        why = "precedent broke, but a near-identical clean launch exists: the outcome turns on the differing detail"
    elif conflicting:
        risk = "high"
        why = "every precedent of this shape materialised"
    else:
        risk = "low"
        why = "precedents of this shape resolved cleanly"
    top = precedents[0]["score"]["proof"]
    conf = min(0.95, 0.35 + 0.12 * top + (0.1 if len(precedents) > 1 else 0.0))
    return {"risk": risk, "confidence": round(conf, 2), "no_precedent": False, "rules": why,
            "conflicting": len(conflicting), "mirrors": len(mirrors)}
