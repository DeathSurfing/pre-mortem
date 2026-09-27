"""Deterministic ranking + the ledger of ignored warnings.

The verdict is produced here, never by an LLM. The LLM only writes the flip sentence.
Every score component is named so the UI can show the arithmetic.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

TREND_PENALTY = {"weakening": -2.0, "stale": -3.0, "new": 0.0, "stable": 0.0, "strengthening": 1.0}
LEDGER_BOOST = 3.0

# Observations produced by consolidation carry EMPTY metadata (verified: `metadata: {}`), so the
# launch id and service have to be recovered from their text, which states them verbatim
# ("Launch L-2026-0034 for payments-service on 2026-04-21 involved ...").
_LAUNCH_RE = re.compile(r"\bL-\d{4}-\d{4}\b")
_DECISION_RE = re.compile(r"\bD-\d{4}-\d{4}\b")
# business domains, recovered from text when a consolidated observation lost its metadata
_BIZ_DOMAINS = ("pricing", "hiring", "vendor", "marketing", "launch", "buildvsbuy",
                "expansion", "operations", "finance", "legal")
_SERVICE_RE = re.compile(r"\bfor ([a-z][a-z0-9-]{2,40}?(?:-service|-api|-worker|-index|-pipeline))\b")
_CLASSES = ("config-only", "dependency-bump", "schema-migration", "flag-flip", "infra-change")

# Consolidated observations describe the change in prose ("a configuration change", "a library upgrade"),
# not with our internal class slug, so a synonym map is required or every observation is dropped by the
# strict service+class filter. Order matters: the most specific phrase wins.
# business decision-type phrases -> corpus slug, for observations that lost their metadata
_BIZ_TYPE_SYNONYMS: tuple[tuple[str, str], ...] = (
    ("renewal discount", "discount"),
    ("discount", "discount"),
    ("price increase", "price-increase"),
    ("packaging", "packaging"),
    ("senior platform engineer", "senior-hire"),
    ("senior hire", "senior-hire"),
    ("backfill", "backfill"),
    ("contractor", "contractor-conversion"),
    ("vendor switch", "vendor-switch"),
    ("vendor renewal", "renewal"),
    ("budget shift", "budget-shift"),
    ("channel test", "channel-test"),
    ("feature launch", "feature-ga"),
    ("general availability", "feature-ga"),
    ("build in house", "build"),
    ("licence", "buy"),
    ("new office", "new-office"),
)

_CLASS_SYNONYMS: tuple[tuple[str, str], ...] = (
    ("configuration-only", "config-only"),
    ("configuration change", "config-only"),
    ("config change", "config-only"),
    ("configuration", "config-only"),
    ("schema migration", "schema-migration"),
    ("migration", "schema-migration"),
    ("feature flag", "flag-flip"),
    ("flag", "flag-flip"),
    ("dependency", "dependency-bump"),
    ("library upgrade", "dependency-bump"),
    ("package upgrade", "dependency-bump"),
    ("infrastructure", "infra-change"),
    ("node pool", "infra-change"),
    ("region", "infra-change"),
)


def recover_attrs(mem: dict) -> dict:
    """Best-effort attributes for a memory, from metadata when present, else parsed from its text.

    Two corpora feed this ranker with different vocabularies, so both are normalised here to one shape:
        deploy corpus:   launch_id / service      / change_class
        business corpus: decision_id / domain     / decision_type
    Normalised keys are always `launch_id` (the citable id), `service` and `change_class`, so `rank()`
    and `verdict()` stay corpus-agnostic.
    """
    meta = dict(mem.get("metadata") or {})
    text = mem.get("text") or ""
    # business corpus -> deploy vocabulary
    if not meta.get("launch_id") and meta.get("decision_id"):
        meta["launch_id"] = meta["decision_id"]
    if not meta.get("service") and meta.get("domain"):
        meta["service"] = meta["domain"]
    if not meta.get("change_class") and meta.get("decision_type"):
        meta["change_class"] = meta["decision_type"]
    if not meta.get("launch_id"):
        hit = _LAUNCH_RE.search(text)
        if hit:
            meta["launch_id"] = hit.group(0)
    if not meta.get("launch_id"):
        hit = _DECISION_RE.search(text)
        if hit:
            meta["launch_id"] = hit.group(0)
    if not meta.get("service"):
        hit = _SERVICE_RE.search(text)
        if hit:
            meta["service"] = hit.group(1)
        else:
            low = text.lower()
            for d in _BIZ_DOMAINS:
                if f" {d} " in f" {low} " or f"{d} decision" in low or f"{d} " in low[:80]:
                    meta["service"] = d
                    break
    if not meta.get("change_class"):
        low = text.lower()
        for phrase, slug in _BIZ_TYPE_SYNONYMS:
            if phrase in low:
                meta["change_class"] = slug
                break
        else:
            for c in _CLASSES:
                if c in low:
                    meta["change_class"] = c
                    break
            else:
                for phrase, slug in _CLASS_SYNONYMS:
                    if phrase in low:
                        meta["change_class"] = slug
                        break
    return meta


# A consolidated observation is a standing belief that many launches share this shape, so it is
# stronger evidence than one raw fact. This is where Hindsight's proof count becomes visible.
TYPE_WEIGHT = {"observation": 2, "experience": 1, "world": 1}


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
    base = TYPE_WEIGHT.get((mem.get("type") or "").lower(), 1)
    if isinstance(mem.get("proof_count"), int) and mem["proof_count"] > 0:
        return max(base, int(mem["proof_count"]))
    return base


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
        attrs = recover_attrs(m)
        m = {**m, "metadata": attrs}
        if not attrs.get("launch_id"):
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
    # verify every attribution, and demote the ones that fail so they cannot be cited as a precedent
    for r in deduped:
        ok, why = verify_attribution(r)
        r["attribution_ok"] = ok
        if not ok:
            r["attribution_note"] = why
            # prefer the same id from a raw fact if one exists in this result set
            raw = next((x for x in out if x["launch_id"] == r["launch_id"] and x.get("memory_type") == "world"), None)
            if raw is not None:
                r.update({"text": raw.get("text"), "memory_type": "world",
                          "source_chunk": raw.get("source_chunk"), "attribution_ok": True,
                          "attribution_note": f"{why}; replaced with the raw record"})
    deduped.sort(key=lambda r: (0 if r.get("attribution_ok") else 1, *sort_key(r)))
    return deduped


_TRUTH_CACHE: dict[str, dict[str, str]] = {}


def ground_truth_index() -> dict[str, dict[str, str]]:
    """id -> {service, change_class, outcome} from the corpus tables, deploy + business.

    Consolidated observations can attribute a change to the wrong id (docs/MODELS.md 9.11). Raw facts
    carry exact metadata, so the corpus is the authority on what an id actually was.
    """
    if _TRUTH_CACHE:
        return _TRUTH_CACHE
    try:
        from .bizcorpus import ground_truth as biz_gt
        from .corpus import ground_truth as dep_gt
        for row in dep_gt()["launches"]:
            _TRUTH_CACHE[row["launch_id"]] = {
                "service": row["service"], "change_class": row["change_class"],
                "outcome": row["outcome"], "is_mirror": str(row["is_mirror"]),
            }
        for row in biz_gt()["decisions"]:
            _TRUTH_CACHE[row["decision_id"]] = {
                "service": row["domain"], "change_class": row["decision_type"],
                "outcome": row["outcome"], "is_mirror": str(row["is_mirror"]),
            }
    except Exception:  # noqa: BLE001
        pass
    return _TRUTH_CACHE


def verify_attribution(p: dict[str, Any]) -> tuple[bool, str]:
    """Is this precedent's id a truthful citation? Returns (ok, reason)."""
    truth = ground_truth_index().get(p.get("launch_id") or "")
    if not truth:
        # an id not in either corpus: it came from the model or a bad extraction, not from our data
        return False, "id is not in the corpus"
    if p.get("memory_type") == "observation":
        # observations have empty metadata, so their service/class were parsed from prose. Check them.
        if p.get("service") and truth["service"] != p["service"]:
            return False, f"observation attributed {truth['service']} work to {p['launch_id']}"
        if p.get("change_class") and truth["change_class"] != p["change_class"]:
            return False, f"observation attributed a {truth['change_class']} change to {p['launch_id']}"
    return True, ""


# Outcome vocabularies differ per corpus and both must count as "this went wrong":
#   deploy corpus:   incident, degraded   (clean = fine)
#   business corpus: bad, mixed           (good = fine)
# A precedent with no recorded outcome counts as neither, so it can support but never inflate risk.
BAD_OUTCOMES = {"incident", "degraded", "bad", "mixed"}
GOOD_OUTCOMES = {"clean", "good"}


def verdict(precedents: list[dict[str, Any]], *, service: str | None, change_class: str | None) -> dict[str, Any]:
    """Risk comes from precedent outcomes, not from the model."""
    if not precedents:
        return {"risk": "unknown", "confidence": 0.0, "no_precedent": True, "rules": "no precedent clears MIN_PROOF"}
    conflicting = [p for p in precedents if not p.get("is_mirror") and p.get("outcome") in BAD_OUTCOMES]
    mirrors = [p for p in precedents if p.get("is_mirror")]
    if conflicting and mirrors:
        risk = "high"
        why = (f"{len(conflicting)} past decision(s) of this shape went badly, and a near-identical one "
               f"went fine: the outcome turns on the differing detail below")
    elif conflicting:
        risk = "high"
        why = f"{len(conflicting)} past decision(s) of this shape went badly, with no counter-example"
    elif mirrors:
        risk = "low"
        why = "the nearest precedent is a near-identical decision that went fine"
    else:
        risk = "medium"
        why = "precedents exist but none records a bad outcome, so this is not evidence of safety"
    top = precedents[0]["score"]["proof"]
    conf = min(0.95, 0.35 + 0.12 * top + (0.1 if len(precedents) > 1 else 0.0))
    if conflicting:
        conf = min(0.95, conf + 0.1)   # a recorded failure is stronger evidence than its proof count implies
    return {"risk": risk, "confidence": round(conf, 2), "no_precedent": False, "rules": why,
            "conflicting": len(conflicting), "mirrors": len(mirrors)}
