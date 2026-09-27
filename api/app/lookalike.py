"""Lookalike assessment: recall precedents, rank them (deterministic), then the LLM writes ONE sentence.

Credit discipline: this path uses `recall` (no LLM) plus a single OpenCode Go call for the flip detail.
`reflect` is a separate, explicit showcase endpoint.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import hindsight
from .config import settings
from .corpus import Pending
from .llm import chat_json, chat_text
from .rank import rank, verdict

FLIP_SCHEMA = {
    "type": "object",
    "required": ["precedent_launch_id", "differentiating_detail"],
    "properties": {
        "precedent_launch_id": {"type": "string"},
        "differentiating_detail": {
            "type": "string",
            "description": "the one parameter difference between the precedent and the pending change that flips the outcome",
        },
        "why_it_matters": {"type": "string"},
        "cited_fix": {"type": "string", "description": "the fix that resolved the incident, quoted from the recalled memories"},
        "no_precedent": {"type": "boolean"},
    },
}

FLIP_SYSTEM = (
    "You are the reasoning step of a change-risk pre-mortem tool. You are given a PENDING change and "
    "RECALLED PRECEDENTS from the same organization's own launch history.\n"
    "Rules:\n"
    "- Use only the recalled memories. Never invent a precedent or a fix.\n"
    "- Name the ONE detail that differs between the pending change and the precedent that broke, if any.\n"
    "- Quote the fix exactly as the memories state it.\n"
    "- If no precedent applies, set no_precedent true and leave differentiating_detail short.\n"
    "Return JSON only."
)

BASELINE_SYSTEM = (
    "You are reviewing a software change for deployment risk. No historical data is available. "
    "Give a short risk review in three short bullets."
)


def query_for(pending: Pending) -> str:
    return (
        f"pending change on {pending.service}: {pending.change_class}. "
        f"{pending.change}. Diff: {pending.diff}"
    )


def _precedent_block(precedents: list[dict[str, Any]]) -> str:
    lines = []
    for p in precedents[:6]:
        facts = p.get("all_texts") or ([p.get("text")] if p.get("text") else [])
        body = "\n".join(f"      - {f}" for f in facts if f)
        # State the outcome explicitly, and say plainly when there is none. A precedent with no recorded
        # outcome is evidence, not a precedent that went well: the model was reading outcome=None as
        # "clean" and describing it that way, which the record does not support.
        if p.get("is_mirror"):
            outcome = "went FINE (near-identical mirror of a decision that broke)"
        elif p["outcome"]:
            outcome = f"outcome={p['outcome']}"
        else:
            outcome = "OUTCOME NOT RECORDED (do not describe this as clean or as a failure)"
        trust = "" if p.get("attribution_ok", True) else (
            " [WARNING: this record's id could not be verified against the corpus; "
            "use its content but do not cite the id as a precedent]")
        lines.append(
            f"- {p['launch_id']} ({p['date']}, {p['service']} / {p['change_class']}, "
            f"{outcome}, evidence={p['proof_count']}, trend={p['trend']}{trust}):\n{body}"
        )
    return "\n".join(lines)


async def assess(pending: Pending, *, memory: bool = True,
                 promoted: set[str] | None = None) -> dict[str, Any]:
    s = settings()
    now = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "memory": memory,
        "preset": pending.key,
        "label": pending.label,
        "pending": {
            "service": pending.service,
            "change_class": pending.change_class,
            "change": pending.change,
            "diff": pending.diff,
        },
        "precedents": [],
        "declined": [],
        "flip": None,
        "facts_used": [],
        "engine": {"ranker": "deterministic", "llm": s.llm_model, "llm_calls": 0},
    }

    recalled: list[dict[str, Any]] = []
    if memory:
        recalled = await hindsight.recall(query_for(pending), budget="mid", max_tokens=1400)

    ranked = rank(recalled, now=now, promoted=promoted, service=pending.service,
                  change_class=pending.change_class, min_proof=s.min_proof)
    result["precedents"] = ranked[:6]
    # nearest-but-insufficient: same service, different class (or vice versa), no proof
    # nearest-but-insufficient: unattributable memories are dropped, not shown as if they were candidates
    declined_ranked = rank(recalled, now=now, promoted=promoted,
                           service=None, change_class=None, min_proof=0)
    seen = {p["launch_id"] for p in result["precedents"]}
    declined = []
    for d in declined_ranked:
        if d["launch_id"] in seen or not d["launch_id"]:
            continue
        if d["service"] == pending.service:
            reason = f"same service, but a different change class ({d['change_class']})"
        elif d["change_class"] == pending.change_class:
            reason = f"same change class, but a different service ({d['service']})"
        else:
            reason = f"different service and change class ({d['service']} / {d['change_class']})"
        declined.append({"launch_id": d["launch_id"], "service": d["service"],
                         "change_class": d["change_class"], "reason": reason,
                         "proof_count": d["proof_count"]})
        if len(declined) >= 3:
            break
    result["declined"] = declined

    v = verdict(result["precedents"], service=pending.service, change_class=pending.change_class)
    result.update({"risk": v["risk"], "confidence": v["confidence"],
                   "no_precedent": v["no_precedent"], "verdict_rules": v["rules"],
                   "conflicting": v.get("conflicting", 0), "mirrors": v.get("mirrors", 0)})

    if not memory:
        text, meta = await chat_text(BASELINE_SYSTEM,
                                     f"Change on {pending.service} ({pending.change_class}): {pending.change}. "
                                     f"Diff: {pending.diff}.", max_tokens=3000)
        result["baseline"] = text
        result["engine"]["llm_calls"] += meta.get("llm_calls", 0)
        return result

    if v["no_precedent"]:
        result["flip"] = None
        result["no_precedent_message"] = (
            "No precedent for this shape of change clears the proof threshold. "
            f"{len(result['declined'])} neighbouring launches were considered and declined."
        )
        result["facts_used"] = [p["launch_id"] for p in result["precedents"]]
        return result

    user = (
        f"PENDING CHANGE\nservice: {pending.service}\nclass: {pending.change_class}\n"
        f"change: {pending.change}\ndiff: {pending.diff}\n\n"
        f"RECALLED PRECEDENTS\n{_precedent_block(result['precedents'])}\n\n"
        "Return JSON with keys: precedent_launch_id, differentiating_detail, why_it_matters, cited_fix, no_precedent."
    )
    parsed, meta = await chat_json(FLIP_SYSTEM, user, max_tokens=3000)
    result["engine"]["llm_calls"] += meta.get("llm_calls", 0)
    result["engine"]["model_used"] = meta.get("model")
    if meta.get("error"):
        result["engine"]["llm_error"] = meta["error"]
    if parsed and parsed.get("no_precedent") and not parsed.get("differentiating_detail"):
        result["flip"] = None
        result["no_precedent_message"] = "the model found no applicable precedent in the recalled set"
    elif parsed:
        result["flip"] = {
            "precedent_launch_id": parsed.get("precedent_launch_id"),
            "differentiating_detail": parsed.get("differentiating_detail"),
            "why_it_matters": parsed.get("why_it_matters"),
            "cited_fix": parsed.get("cited_fix"),
        }
    result["facts_used"] = sorted({p["launch_id"] for p in result["precedents"] if p["launch_id"]})
    result["engine"]["attribution_unverified"] = [
        p["launch_id"] for p in result["precedents"] if not p.get("attribution_ok", True)]
    if result["flip"] and result["flip"].get("precedent_launch_id"):
        cited = result["flip"]["precedent_launch_id"]
        if cited not in result["facts_used"]:
            # the model cited something it was not given: flag it rather than hide it
            result["engine"]["citation_warning"] = f"model cited {cited} which was not in the recalled set"
    return result


async def assess_reflect(pending: Pending, *, promoted: set[str] | None = None) -> dict[str, Any]:
    """The showcase path: let Hindsight answer it itself. Costs real tokens; use sparingly."""
    s = settings()
    base = await assess(pending, memory=True, promoted=promoted)
    schema = {
        "type": "object",
        "required": ["precedent_launch_id", "differentiating_detail"],
        "properties": FLIP_SCHEMA["properties"],
    }
    r = await hindsight.reflect(
        query=(f"A pending {pending.change_class} change on {pending.service}: {pending.change}. "
               f"Name the closest precedent launch id and the ONE detail that differs in a way that changes the outcome."),
        response_schema=schema,
        budget="low",
    )
    base["reflect"] = r
    base["engine"]["engine"] = "hindsight-reflect"
    base["engine"]["model_used"] = f"hindsight-bank-model ({s.llm_model} for our own copy)"
    return base
