"""Prompt history: record every prompt, cross-reference it, and gate what reaches Hindsight.

The rule this file enforces: **a prompt is recorded and vectorised, never retained.** `treat all prompts
as new knowledge` is deliberately NOT honoured against Hindsight; it is honoured against the prompt store,
which is the right home for a typed question. Only `POST /api/biz/history/commit` writes to Hindsight, and
only when a person pressed the button.

Cross-referencing: each new prompt is compared against every prior prompt by cosine similarity. Weak
matches are returned with `above_cutoff: false` rather than hidden, so a first-of-its-kind prompt reads as
new instead of as having a precedent it does not have.

Routes live under `/api/biz/history`, NOT `/api/biz/prompts`: the latter is the existing presets endpoint
(`main.biz_prompts`), and a router at the same path shadows it. That shadowing swapped the preset list for
the store object and crashed the page during hydration, so the prefix is deliberately distinct.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import prompts as ps

log = logging.getLogger("premortem.prompt_history")

router = APIRouter(prefix="/api/biz/history", tags=["prompts"])

store = ps.PromptStore()


class RecallBody(BaseModel):
    prompt: str
    limit: int = Field(5, ge=1, le=20)
    exclude_id: str | None = None


class CommitBody(BaseModel):
    id: str | None = None
    prompt: str | None = None
    domain: str | None = None
    decision_type: str | None = None
    risk: str | None = None
    # Set once the user has reviewed the draft. Absent means "just draft it".
    draft: DecisionDraft | None = None


class DecisionDraft(BaseModel):
    """The editable shape of a decision the user is adding. One field per corpus field."""
    decision: str = ""
    rationale: str = ""
    result: str = ""
    lesson: str = ""
    outcome: str = ""          # "" | good | mixed | bad
    owner: str = ""
    scale: str = ""
    context: str = ""
    domain: str = ""
    decision_type: str = ""


class DraftBody(BaseModel):
    prompt: str
    domain: str | None = None
    decision_type: str | None = None
    risk: str | None = None
    headline: str | None = None


# The taxonomy the seeded corpus uses. Constrained on purpose: an off-vocabulary domain would still be
# retained, but it could never match a corpus record in lookalike, so the new decision would be
# unretrievable in practice. See bizcorpus for the source of truth.
_DOMAINS = ["pricing", "hiring", "vendor", "marketing", "launch", "buildvsbuy", "compliance",
            "security", "partnership", "ops"]
_TYPES = ["discount", "packaging", "price-increase", "renewal", "vendor-switch", "senior-hire",
          "backfill", "contractor-conversion", "budget-shift", "channel-test", "feature-ga", "build",
          "buy", "audit-finding", "incident-response", "reseller-agreement", "datacenter-region"]

# Drafting is explicitly forbidden from inventing a result or an outcome. A decision still being weighed
# has neither, and a fabricated one would put a false precedent into the store the product cites.
DRAFT_SYSTEM = (
    "You turn a business-decision review into a storable decision record. You are given the decision and "
    "the review the tool already produced about it.\n\n"
    "Rules, all absolute:\n"
    "1. Never invent a result, an outcome, a number, or a date. If the decision has not been carried out "
    "yet, or no result is known, leave `result` as an empty string and `outcome` as an empty string. That "
    "is the expected and correct answer for a decision the user is still considering.\n"
    "2. `outcome` MUST be \"\" unless the provided text states what actually happened. Allowed non-empty "
    "values are exactly: good, mixed, bad. Never guess between them.\n"
    "3. Fill only from the given text. Do not add outside knowledge, market context, or plausible detail.\n"
    "4. `decision` is one sentence: what is being decided, in the third person, past or present tense as "
    "the text supports.\n"
    "5. `rationale` is why, taken from the review or the user's wording. Empty if the text gives none.\n"
    "6. `lesson` only if the text records a lesson. Otherwise empty.\n"
    "7. `domain` and `decision_type` MUST be chosen from the provided lists, or left empty. Never invent "
    "a new one, and never use a value outside the list.\n"
    "8. `owner`, `scale` and `context` are empty unless the text states them.\n\n"
    "Return JSON with exactly these keys: decision, rationale, result, lesson, outcome, owner, scale, "
    "context, domain, decision_type."
)


async def draft_decision(*, prompt: str, domain: str | None, decision_type: str | None,
                         risk: str | None, headline: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Draft a decision record from the review, for the user to edit before adding.

    Returns (draft, meta). The draft is always a complete, usable shape: if the model is unavailable the
    caller still gets the decision text, so the user can fill it in rather than being blocked.
    """
    from . import llm

    fallback = {"decision": prompt.strip(), "rationale": "", "result": "", "lesson": "", "outcome": "",
                "owner": "", "scale": "", "context": "", "domain": domain or "",
                "decision_type": decision_type or ""}
    if not headline and not prompt.strip():
        return fallback, {"drafted": False, "reason": "nothing to draft from"}

    user = (
        f"The decision under review (the user's own words):\n{prompt.strip()}\n\n"
        f"The tool classified it as: domain={domain or 'unknown'}, type={decision_type or 'unknown'}, "
        f"risk={risk or 'unknown'}.\n\n"
        f"The review's headline: {headline or '(none produced)'}\n\n"
        f"Allowed domain values: {', '.join(_DOMAINS)}\n"
        f"Allowed decision_type values: {', '.join(_TYPES)}\n"
    )
    parsed, meta = await llm.chat_json(DRAFT_SYSTEM, user, max_tokens=1200)
    if not parsed:
        return fallback, {**meta, "drafted": False}

    out = dict(fallback)
    for k in out:
        v = parsed.get(k)
        if isinstance(v, str):
            out[k] = v.strip()
    # Guard the two fields where a model error is expensive: an invented outcome, or a label outside the
    # taxonomy that would make the record unretrievable.
    if out["outcome"].lower() not in ("good", "mixed", "bad"):
        out["outcome"] = ""
    else:
        out["outcome"] = out["outcome"].lower()
    if out["domain"] not in _DOMAINS:
        out["domain"] = domain if domain in _DOMAINS else ""
    if out["decision_type"] not in _TYPES:
        out["decision_type"] = decision_type or ""
    if not out["decision"].strip():
        out["decision"] = prompt.strip()
    return out, {**meta, "drafted": True}


def record_and_crossref(text: str, *, domain: str | None, decision_type: str | None,
                        mode: str | None = None, risk: str | None = None,
                        confidence: float | None = None,
                        session_id: str | None = None) -> dict[str, Any]:
    """Vectorise the prompt, store it, and return its nearest prior prompts.

    Called from the review stream. Never raises and never blocks the review: if the store is down, the
    caller gets `{"available": False}` and the answer streams as normal.
    """
    if not store.ensure_schema():
        return {"available": False, "error": store.error, "recorded_id": None, "similar": []}

    vector = ps.embed(text)
    pid = store.record(prompt=text, domain=domain, decision_type=decision_type, mode=mode, risk=risk,
                       confidence=confidence, session_id=session_id, embedding=vector)

    # Cross-reference against the prompt that came before this one. Find neighbours first, then record,
    # so a prompt is never returned as its own nearest match.
    similar: list[dict[str, Any]] = []
    if vector:
        similar = store.similar(vector, limit=5, exclude_id=pid)

    return {
        "available": True,
        "recorded_id": pid,
        "embedded": vector is not None,
        "model": ps.EMBED_MODEL,
        "similar": similar,
    }


@router.get("")
async def list_prompts(limit: int = 20) -> dict[str, Any]:
    """Recent prompts, newest first. `committed` says which ones are in the knowledge base."""
    if not store.ensure_schema():
        return {"available": False, "error": store.error, "items": [], "stats": store.stats()}
    return {"available": True, "items": store.recent(limit=limit), "stats": store.stats()}


@router.get("/stats")
async def stats() -> dict[str, Any]:
    return {"store": store.stats(), "embedder": ps.embedding_status()}


@router.post("/recall")
async def recall(body: RecallBody) -> dict[str, Any]:
    """Cross-reference an arbitrary prompt against the stored ones, without recording it."""
    if not store.ensure_schema():
        raise HTTPException(503, f"prompt store unavailable: {store.error}")
    vector = ps.embed(body.prompt)
    if vector is None:
        raise HTTPException(503, f"embedding unavailable: {ps.embedding_status().get('error')}")
    return {"similar": store.similar(vector, limit=body.limit, exclude_id=body.exclude_id)}


@router.post("/draft")
async def draft(body: DraftBody) -> dict[str, Any]:
    """Draft a decision record from the review, for the user to edit before adding.

    Always returns a complete, usable draft. If the model is unavailable the decision text is filled from
    the user's own words and the rest is empty, so the user can type it in rather than being blocked.
    """
    d, meta = await draft_decision(prompt=body.prompt, domain=body.domain,
                                   decision_type=body.decision_type, risk=body.risk,
                                   headline=body.headline)
    return {"draft": d, "drafted": bool(meta.get("drafted")),
            "domains": _DOMAINS, "decision_types": _TYPES,
            "note": ("Filled from the review. Anything the review did not state is left blank on purpose: a "
                     "decision that has not been carried out yet has no result, and inventing one would put "
                     "a false precedent into the history this tool cites.")}


@router.post("/commit")
async def commit(body: CommitBody) -> dict[str, Any]:
    """The gate. Only here does a decision enter the company's knowledge base, and only on a human yes.

    Two shapes, both landing in Hindsight as a decision record rather than a chat log:

    - with `draft`: the user has filled in / edited the decision record, and that is what is stored. This is
      the "add this decision" path, and it captures the summary, rationale, result and lesson.
    - without `draft`: the older, thinner path, which stores the prompt as a decision record.

    Either way the outcome is only recorded if the user asserted one. Nothing here infers a result.
    """
    if not body.id and not body.prompt:
        raise HTTPException(422, "provide an id or a prompt")

    if not store.ensure_schema():
        raise HTTPException(503, f"prompt store unavailable: {store.error}")

    row: dict[str, Any] | None = None
    if body.id:
        row = next((r for r in store.recent(limit=500) if str(r["id"]) == body.id), None)
        if row is None:
            raise HTTPException(404, f"unknown prompt id {body.id}")

    text = body.prompt or (row or {}).get("prompt") or ""
    domain = body.domain or (row or {}).get("domain")
    dtype = body.decision_type or (row or {}).get("decision_type")
    risk = body.risk or (row or {}).get("risk")

    if body.draft is not None:
        d = body.draft
        if not d.decision.strip():
            raise HTTPException(422, "the decision text is empty")
        decision_id, doc = ps.decision_document_text(
            decision=d.decision.strip(),
            domain=(d.domain or domain),
            decision_type=(d.decision_type or dtype),
            rationale=d.rationale, result=d.result, lesson=d.lesson, outcome=d.outcome,
            owner=d.owner, scale=d.scale, context=d.context,
            source_prompt=text or None,
        )
        context = "user-added business decision"
    else:
        if not text.strip():
            raise HTTPException(422, "the prompt to commit is empty")
        decision_id, doc = ps.commit_document_text(text, domain=domain, decision_type=dtype, risk=risk)
        context = "user-committed business decision"

    # Import here, not at module scope: keeps this router importable without a Hindsight key.
    from . import config, hindsight
    try:
        r = await hindsight.client().aretain_batch(
            bank_id=config.settings().biz_bank_id,
            items=[{"content": doc["text"], "context": context,
                    "timestamp": None, "document_id": decision_id, "metadata": doc["metadata"]}],
            retain_async=False,
        )
    except Exception as e:  # noqa: BLE001 - a failed commit must be reported, not swallowed
        log.warning("commit retain failed: %s: %s", type(e).__name__, e)
        raise HTTPException(502, f"Hindsight retain failed: {type(e).__name__}: {e}") from e

    if body.id:
        store.commit(body.id, decision_id)

    return {"committed": True, "decision_id": decision_id, "metadata": doc["metadata"],
            "outcome_recorded": bool(body.draft and body.draft.outcome),
            "hindsight": str(r)[:200]}
