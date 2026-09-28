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


@router.post("/commit")
async def commit(body: CommitBody) -> dict[str, Any]:
    """The gate. Only here does a prompt enter the company's knowledge base, and only on a human yes.

    Retains to Hindsight as a decision record (not a chat log), then marks the row committed with the
    Hindsight document id so the two can be reconciled later.
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
    if not text.strip():
        raise HTTPException(422, "the prompt to commit is empty")

    domain = body.domain or (row or {}).get("domain")
    dtype = body.decision_type or (row or {}).get("decision_type")
    risk = body.risk or (row or {}).get("risk")

    decision_id, doc = ps.commit_document_text(text, domain=domain, decision_type=dtype, risk=risk)

    # Import here, not at module scope: keeps this router importable without a Hindsight key.
    from . import config, hindsight
    try:
        r = await hindsight.client().aretain_batch(
            bank_id=config.settings().biz_bank_id,
            items=[{"content": doc["text"], "context": "user-committed business decision",
                    "timestamp": None, "document_id": decision_id, "metadata": doc["metadata"]}],
            retain_async=False,
        )
    except Exception as e:  # noqa: BLE001 - a failed commit must be reported, not swallowed
        log.warning("commit retain failed: %s: %s", type(e).__name__, e)
        raise HTTPException(502, f"Hindsight retain failed: {type(e).__name__}: {e}") from e

    if body.id:
        store.commit(body.id, decision_id)

    return {"committed": True, "decision_id": decision_id, "metadata": doc["metadata"],
            "hindsight": str(r)[:200]}
