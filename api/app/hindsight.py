"""Hindsight access layer: bank bootstrap, seed, recall, reflect, stats.

Verified against Hindsight Cloud API 0.10.1 (docs/MODELS.md section 9):
 - `banks.*` are async; use the async methods directly under FastAPI (never asyncio.run).
 - `recall` costs no LLM. `retain`/`reflect` do. Recall is the default path for that reason.
 - `banks.test_bank_llm` 404s on Cloud; guard on `features.bank_llm_health`.
 - `query_timestamp` does NOT filter results, so no-lookahead is enforced by staged ingestion plus our own
   `occurred_start` filter in replay.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

from hindsight_client_api.models.create_bank_request import CreateBankRequest
from hindsight_client_api.models.disposition_traits import DispositionTraits

from .config import BANK_ID, client, settings

log = logging.getLogger("premortem.hindsight")

MISSION = (
    "I am a change-risk pre-mortem agent. I recall what this organization's own past launches did and I "
    "argue from precedent. I never assert a cause I cannot cite to a launch ID."
)

DIRECTIVES = [
    "Never assert a precedent without citing a launch ID.",
    "Never state a root cause that is not linked to a retained fix.",
    "Always report the count of precedents behind a claim, including when it is zero.",
    "Never invent a similarity when no precedent matches; say no precedent instead.",
    "Never give instructions to deploy, ship, or approve anything.",
]

RETAIN_INSTRUCTIONS = (
    "This is a post-deploy change record. Extract as separate facts: the change made, the exact diff, the "
    "symptom with its numbers, the outcome and severity, and the fix that resolved it. Preserve service "
    "names, parameter names, IDs and numeric values exactly as written. Do not summarize away the "
    "parameter that differs between one launch and another."
)


async def ensure_bank() -> dict[str, Any]:
    """Idempotent bank create/update: mission, disposition, retain instructions, then directives.

    Note: CreateBankRequest has no `directives` field. Directives are a separate resource
    (`create_directive(bank_id, name, content, priority)`), and it is not idempotent per call,
    so we reconcile against the existing list first.
    """
    s = settings()
    req = CreateBankRequest(
        name="pre-mortem",
        mission=MISSION,
        disposition=DispositionTraits(skepticism=4, literalism=5, empathy=2),
        enable_observations=True,
        retain_custom_instructions=RETAIN_INSTRUCTIONS,
    )
    await client().banks.create_or_update_bank(s.bank_id, req)

    existing = await list_directives()
    have = {d["content"] for d in existing}
    created = []
    for i, text in enumerate(DIRECTIVES):
        if text in have:
            continue
        try:
            await client().acreate_directive(bank_id=s.bank_id, name=f"guardrail-{i + 1}",
                                             content=text, priority=10 - i)
            created.append(text[:40])
        except Exception as e:  # noqa: BLE001
            log.warning("directive create failed: %s", e)

    cfg = await client().banks.get_bank_config(s.bank_id)
    out = cfg if isinstance(cfg, dict) else cfg.to_dict()
    out["directives_created"] = created
    out["directives_total"] = len(await list_directives())
    return out


async def list_directives() -> list[dict[str, Any]]:
    try:
        r = await client().alist_directives(settings().bank_id)
        items = getattr(r, "items", None) or []
        return [{"name": getattr(d, "name", None), "content": getattr(d, "content", None),
                 "priority": getattr(d, "priority", None), "is_active": getattr(d, "is_active", None)}
                for d in items]
    except Exception as e:  # noqa: BLE001
        log.warning("list_directives failed: %s", e)
        return []


async def agent_stats() -> dict[str, Any]:
    s = await client().banks.get_agent_stats(settings().bank_id)
    return s if isinstance(s, dict) else s.to_dict()


async def features() -> dict[str, Any]:
    """get_version lives on the monitoring API and is async; await it explicitly."""
    try:
        # Use the async variant: the sync get_version wrapper calls loop.run_until_complete, which
        # raises "This event loop is already running" inside FastAPI's loop.
        v = await client().aget_version()
        f = getattr(v, "features", None)
        return {"api_version": getattr(v, "api_version", None),
                "observations": getattr(f, "observations", None),
                "bank_llm_health": bool(getattr(f, "bank_llm_health", False))}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:200]}


async def health_check_llm() -> dict[str, Any]:
    """test_bank_llm when the server supports it, else a tiny reflect as a proxy."""
    f = await features()
    if f.get("bank_llm_health"):
        try:
            return {"method": "test_bank_llm", "ok": True,
                    "detail": str(await client().banks.test_bank_llm(settings().bank_id))[:200]}
        except Exception as e:  # noqa: BLE001
            return {"method": "test_bank_llm", "ok": False, "detail": f"{type(e).__name__}: {e}"[:200]}
    # Fallback probe. One cheap reflect; only run it when explicitly asked.
    try:
        r = await client().areflect(bank_id=settings().bank_id, query="Reply with the single word ok.",
                                    budget="low", max_tokens=32)
        return {"method": "reflect-probe", "ok": bool(getattr(r, "text", None)),
                "detail": (getattr(r, "text", "") or "")[:80]}
    except Exception as e:  # noqa: BLE001
        return {"method": "reflect-probe", "ok": False, "detail": f"{type(e).__name__}: {e}"[:200]}


async def seed(launches) -> dict[str, Any]:
    """Retain every launch. One document per launch, timestamped at the launch date."""
    s = settings()
    items = [
        {
            "content": l.text(),
            "context": "post-deploy change record",
            "timestamp": l.date.isoformat(),
            "document_id": l.launch_id,
            "metadata": l.metadata(),
        }
        for l in launches
    ]
    r = await client().aretain_batch(bank_id=s.bank_id, items=items, retain_async=False)
    txt = str(r)
    tokens = None
    usage = getattr(r, "usage", None)
    if usage is not None:
        tokens = getattr(usage, "total_tokens", None)
    return {"retained": len(items), "raw": txt[:200], "tokens": tokens}


async def list_documents(limit: int = 100) -> list[dict[str, Any]]:
    try:
        r = await client().documents.list_documents(settings().bank_id, limit=limit)
        items = getattr(r, "items", None) or []
        return [{"id": getattr(d, "id", None), "created_at": str(getattr(d, "created_at", ""))} for d in items]
    except Exception as e:  # noqa: BLE001
        return [{"error": f"{type(e).__name__}: {e}"}]


async def delete_documents(doc_ids: list[str]) -> int:
    n = 0
    for d in doc_ids:
        try:
            await client().documents.delete_document(settings().bank_id, d)
            n += 1
        except Exception as e:  # noqa: BLE001
            log.warning("delete %s failed: %s", d, e)
    return n


async def recall(query: str, *, types: list[str] | None = None, budget: str = "mid",
                 max_tokens: int = 1200, include_chunks: bool = True,
                 include_entities: bool = True) -> list[dict[str, Any]]:
    """Retrieval only. No LLM cost. Returns normalized dicts."""
    r = await client().arecall(
        bank_id=settings().bank_id,
        query=query,
        types=types or ["world", "experience", "observation"],
        budget=budget,
        max_tokens=max_tokens,
        include_chunks=include_chunks,
        include_entities=include_entities,
    )
    chunks = getattr(r, "chunks", None) or {}
    out = []
    for m in getattr(r, "results", []) or []:
        cid = getattr(m, "chunk_id", None)
        chunk = None
        if cid and cid in chunks:
            chunk = (getattr(chunks[cid], "text", None) or "")[:600]
        out.append({
            "id": getattr(m, "id", None),
            "text": getattr(m, "text", None),
            "type": getattr(m, "type", None),
            "metadata": getattr(m, "metadata", None) or {},
            "occurred_start": getattr(m, "occurred_start", None),
            "document_id": getattr(m, "document_id", None),
            "chunk": chunk,
        })
    return out


async def wait_for_observations(timeout_s: int = 180, poll_s: int = 10) -> dict[str, Any]:
    """Consolidation is a background job: observations appear AFTER retain, not during it.

    Verified behaviour: immediately after seeding, `total_observations` is 0 and
    `pending_consolidation` is non-zero. `recover_consolidation()` nudges it, then it still needs
    wall-clock time. Poll until observations exist, because the trend badges and proof counts in the
    UI come from them. Free calls (stats only), so polling costs nothing.
    """
    import asyncio
    import time as _t
    started = _t.time()
    last: dict[str, Any] = {}
    while _t.time() - started < timeout_s:
        try:
            st = await agent_stats()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        last = {"total_observations": st.get("total_observations"),
                "pending_consolidation": st.get("pending_consolidation"),
                "nodes_by_fact_type": st.get("nodes_by_fact_type")}
        if (st.get("total_observations") or 0) > 0:
            return {"ok": True, "waited_s": round(_t.time() - started, 1), **last}
        await recover_consolidation()
        await asyncio.sleep(poll_s)
    return {"ok": False, "timed_out_s": timeout_s, **last}


async def recover_consolidation() -> dict[str, Any]:
    try:
        r = await client().banks.recover_consolidation(settings().bank_id)
        return {"ok": True, "detail": str(r)[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"[:200]}


async def clear_observations() -> dict[str, Any]:
    try:
        r = await client().banks.clear_observations(settings().bank_id)
        return {"ok": True, "detail": str(r)[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"[:200]}


async def reflect(query: str, *, context: str | None = None, budget: str = "low",
                  response_schema: dict | None = None, max_tokens: int = 700) -> dict[str, Any]:
    """The one call that costs real tokens. Used for the showcase beat only."""
    r = await client().areflect(
        bank_id=settings().bank_id,
        query=query,
        context=context,
        budget=budget,
        response_schema=response_schema,
        include_facts=True,
        max_tokens=max_tokens,
    )
    based = getattr(r, "based_on", None)
    mems = []
    if based is not None:
        for m in (getattr(based, "memories", None) or []):
            mems.append({"id": getattr(m, "id", None), "text": (getattr(m, "text", None) or "")[:300]})
    return {
        "text": getattr(r, "text", None),
        "structured": getattr(r, "structured_output", None),
        "structured_error": getattr(r, "structured_output_error", None),
        "based_on": mems,
        "usage": str(getattr(r, "usage", ""))[:200],
    }


async def timeseries(period: str = "month", time_field: str = "occurred_start") -> list[dict[str, Any]]:
    try:
        r = await client().banks.get_memories_timeseries(settings().bank_id, period, time_field)
        return [{"time": getattr(b, "time", None), "world": getattr(b, "world", 0),
                 "experience": getattr(b, "experience", 0), "observation": getattr(b, "observation", 0)}
                for b in (getattr(r, "buckets", None) or [])]
    except Exception as e:  # noqa: BLE001
        return [{"error": f"{type(e).__name__}: {e}"}]


async def preview_prompt(operation: str = "retain") -> dict[str, Any]:
    from hindsight_client_api.models import PromptPreviewRequest
    try:
        r = await client().banks.preview_prompt(settings().bank_id, PromptPreviewRequest(operation=operation))
        d = r if isinstance(r, dict) else r.to_dict()
        msgs = []
        for m in (d.get("messages") or []):
            mm = m if isinstance(m, dict) else m.to_dict()
            msgs.append({"role": mm.get("role"), "content": (mm.get("content") or "")[:1500]})
        return {"strategy": d.get("strategy"), "strategies": d.get("strategies"),
                "messages": msgs, "skipped_reason": d.get("skipped_reason")}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:300]}


__all__ = [
    "BANK_ID", "MISSION", "DIRECTIVES", "ensure_bank", "agent_stats", "features",
    "health_check_llm", "seed", "list_documents", "delete_documents", "recall", "list_directives",
    "wait_for_observations",
    "recover_consolidation", "clear_observations", "reflect", "timeseries", "preview_prompt",
]
