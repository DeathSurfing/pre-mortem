"""FastAPI surface. Owns every Hindsight call; the browser never talks to Hindsight directly."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import (bizcorpus, bizledger, bizlookalike, hindsight, laya_client, ledger, lookalike,
               replay)
from .config import (BIZ_DIRECTIVES, BIZ_MISSION, BIZ_RETAIN_INSTRUCTIONS, settings)
from .corpus import ground_truth, PRESETS, PRESET_BY_KEY, corpus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("premortem")

app = FastAPI(title="pre-mortem", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class AssessBody(BaseModel):
    preset: str
    memory: bool = True
    engine: str = "recall"  # recall (free) | reflect (costs tokens)
    use_ledger: bool = True


@app.get("/health")
async def health() -> dict[str, Any]:
    """Readiness: config sane + Hindsight reachable + bank readable."""
    s = settings()
    out: dict[str, Any] = {
        "ok": True,
        "problems": s.problems(),
        "bank_id": s.bank_id,
        "hindsight_url": s.hindsight_url,
        "models": {"llm": s.llm_model, "fallback": s.llm_fallback_model, "min_proof": s.min_proof},
    }
    out["features"] = await hindsight.features()
    out["laya"] = laya_client.status()
    try:
        cfg = await hindsight.ensure_bank()
        out["bank"] = {
            "mission_set": bool(cfg.get("mission") or (cfg.get("config") or {}).get("mission")),
            "disposition": {
                "skepticism": (cfg.get("config") or {}).get("disposition_skepticism"),
                "literalism": (cfg.get("config") or {}).get("disposition_literalism"),
                "empathy": (cfg.get("config") or {}).get("disposition_empathy"),
            },
            "directives_total": len(await hindsight.list_directives()),
            "corpus_expected": len(corpus()),
        }
        out["documents"] = await hindsight.list_documents(limit=100)
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["error"] = f"{type(e).__name__}: {e}"[:400]
    return out


@app.get("/api/presets")
async def presets() -> list[dict[str, Any]]:
    return [{"key": p.key, "label": p.label, "service": p.service, "change_class": p.change_class,
             "change": p.change, "diff": p.diff, "expect": p.expect} for p in PRESETS]


@app.post("/api/assess")
async def assess(body: AssessBody) -> dict[str, Any]:
    p = PRESET_BY_KEY.get(body.preset)
    if p is None:
        raise HTTPException(404, f"unknown preset {body.preset}")
    promoted = await ledger.promoted_classes() if (body.use_ledger and body.memory) else set()
    if body.engine == "reflect" and body.memory:
        out = await lookalike.assess_reflect(p, promoted=promoted)
    else:
        out = await lookalike.assess(p, memory=body.memory, promoted=promoted)
    out["ledger_promoted"] = sorted(promoted)
    return out


@app.get("/api/ledger")
async def get_ledger() -> dict[str, Any]:
    return await ledger.summary()


@app.post("/api/seed")
async def seed(force: bool = Query(False, description="delete existing documents first")) -> dict[str, Any]:
    """Corpus seed. 40 retains, each costing extraction tokens. Run deliberately, not casually."""
    ls = corpus()
    out: dict[str, Any] = {"bank": None, "seed": None, "ledger": None, "stats_before": None}
    try:
        out["stats_before"] = await hindsight.agent_stats()
    except Exception:  # noqa: BLE001
        pass
    if force:
        docs = [d for d in await hindsight.list_documents(limit=200) if d.get("id")]
        out["deleted"] = await hindsight.delete_documents([d["id"] for d in docs])
    out["bank"] = await hindsight.ensure_bank()
    out["seed"] = await hindsight.seed(ls)
    out["ledger"] = await ledger.seed_ledger()
    out["consolidate"] = await hindsight.recover_consolidation()
    # observations are a background job; wait so the UI has trends and proof counts immediately
    out["observations"] = await hindsight.wait_for_observations()
    out["stats_after"] = await hindsight.agent_stats()
    # ground truth is computed from the corpus table, never from an LLM
    DATA_DIR.mkdir(exist_ok=True)
    gt = ground_truth()
    (DATA_DIR / "ground_truth.json").write_text(json.dumps(gt, indent=1))
    out["ground_truth_totals"] = gt["totals"]
    return out


@app.post("/api/consolidate")
async def consolidate(wait: bool = Query(True)) -> dict[str, Any]:
    """Nudge consolidation and, by default, wait until observations actually exist."""
    rec = await hindsight.recover_consolidation()
    waited = await hindsight.wait_for_observations() if wait else None
    return {"recover": rec, "observations": waited, "stats": await hindsight.agent_stats()}


@app.post("/api/replay")
async def run_replay(max_launches: int | None = None) -> dict[str, Any]:
    return await replay.run_replay(max_launches=max_launches)


@app.get("/api/metrics")
async def metrics() -> dict[str, Any]:
    p = DATA_DIR / "replay.json"
    if not p.exists():
        raise HTTPException(409, "no replay cached yet; POST /api/replay first")
    return json.loads(p.read_text())


@app.get("/api/bank")
async def bank() -> dict[str, Any]:
    return {
        "config": await hindsight.ensure_bank(),
        "directives": await hindsight.list_directives(),
        "stats": await hindsight.agent_stats(),
        "timeseries": await hindsight.timeseries("month", "occurred_start"),
        "features": await hindsight.features(),
    }


@app.get("/api/prompt-preview")
async def prompt_preview(operation: str = "retain") -> dict[str, Any]:
    return await hindsight.preview_prompt(operation)


@app.get("/api/ground-truth")
async def gt() -> dict[str, Any]:
    p = DATA_DIR / "ground_truth.json"
    return json.loads(p.read_text()) if p.exists() else ground_truth()


class RedflagBody(BaseModel):
    prompt: str = ""
    preset: str | None = None          # optional canned prompt key (A/B/C)
    memory: bool = True
    engine: str = "recall"             # recall (1 LLM call) | reflect (Hindsight answers it itself)
    use_ledger: bool = True
    seed_classification: str | None = None   # "domain:decision_type", for tests only


# ---------------------------------------------------------------- business decisions

@app.get("/api/biz/prompts")
async def biz_prompts() -> list[dict[str, Any]]:
    return [{"key": p.key, "label": p.label, "text": p.text,
             "expect_domain": p.expect_domain, "expect_type": p.expect_type, "expect": p.expect}
            for p in bizcorpus.PROMPTS]


@app.post("/api/biz/redflag")
async def biz_redflag(body: RedflagBody) -> dict[str, Any]:
    text = body.prompt
    if body.preset and not text:
        match = bizcorpus.PROMPT_BY_KEY.get(body.preset)
        if match is None:
            raise HTTPException(404, f"unknown preset {body.preset}")
        text = match.text
    if not text.strip():
        raise HTTPException(422, "provide a prompt or a preset key")
    promoted = await bizledger.promoted_classes() if (body.use_ledger and body.memory) else set()
    if body.engine == "reflect" and body.memory:
        out = await bizlookalike.redflag_reflect(text, promoted=promoted)
    else:
        out = await bizlookalike.redflag(text, memory=body.memory, promoted=promoted,
                                         seed=body.seed_classification)
    out["ledger_promoted"] = sorted(promoted)
    return out


@app.get("/api/biz/redflag/stream")
async def biz_redflag_stream(prompt: str = Query("", description="the decision text"),
                             preset: str | None = None,
                             use_ledger: bool = True):
    """Server-sent events: status -> classify -> precedents -> verdict -> delta* -> done.

    Streaming matters here because the pipeline has real stages (Laya + extract, recall, then prose), and
    the UI can show each one instead of a spinner. The verdict arrives before the prose, so the risk
    banner renders while the text is still being written.
    """
    text = prompt
    if preset and not prompt.strip():
        match = bizcorpus.PROMPT_BY_KEY.get(preset)
        if match is None:
            raise HTTPException(404, f"unknown preset {preset}")
        text = match.text
    if not text.strip():
        raise HTTPException(422, "provide a prompt")
    promoted = await bizledger.promoted_classes() if use_ledger else set()

    async def gen():
        yield "data: " + json.dumps({"type": "status", "message": "connected", "step": "start"}) + "\n\n"
        if promoted:
            yield "data: " + json.dumps({"type": "ledger", "promoted": sorted(promoted)}) + "\n\n"
        async for chunk in bizlookalike.redflag_stream(text, promoted=promoted):
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


class Turn(BaseModel):
    """One prior message in the conversation."""

    role: str
    content: str


class StreamRequest(BaseModel):
    prompt: str = ""
    preset: str | None = None
    use_ledger: bool = True
    """Prior turns, oldest first. Presence makes this message a follow-up: it is answered conversationally
    with this context rather than reviewed from scratch."""
    history: list[Turn] = []


@app.post("/api/biz/redflag/stream")
async def biz_redflag_stream_post(body: StreamRequest):
    """POST variant of the SSE stream, so a follow-up can carry the conversation.

    A GET with the whole history in the query string would break on length, and history is the point: a
    follow-up only makes sense with the review it is following up on.
    """
    text = body.prompt
    if body.preset and not text.strip():
        match = bizcorpus.PROMPT_BY_KEY.get(body.preset)
        if match is None:
            raise HTTPException(404, f"unknown preset {body.preset}")
        text = match.text
    if not text.strip():
        raise HTTPException(422, "provide a prompt")

    history = [{"role": h.role, "content": h.content} for h in body.history][-12:]
    promoted = await bizledger.promoted_classes() if body.use_ledger else set()

    async def gen():
        yield "data: " + json.dumps({"type": "status", "message": "connected", "step": "start"}) + "\n\n"
        if promoted:
            yield "data: " + json.dumps({"type": "ledger", "promoted": sorted(promoted)}) + "\n\n"
        async for chunk in bizlookalike.redflag_stream(text, promoted=promoted, history=history):
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


@app.get("/api/biz/ledger")
async def biz_ledger() -> dict[str, Any]:
    return await bizledger.summary()


@app.get("/api/biz/bank")
async def biz_bank() -> dict[str, Any]:
    bid = settings().biz_bank_id
    return {
        "bank_id": bid,
        "config": await hindsight.ensure_bank(bid, mission=BIZ_MISSION,
                                             instructions=BIZ_RETAIN_INSTRUCTIONS,
                                             name="business decisions"),
        "directives": await hindsight.list_directives(bid),
        "stats": await hindsight.agent_stats(bid),
        "documents": await hindsight.list_documents(limit=200, bank_id=bid),
    }


@app.post("/api/biz/seed")
async def biz_seed(force: bool = Query(False, description="delete existing documents first")) -> dict[str, Any]:
    """Seed the business corpus. 72 retains, each costing extraction tokens."""
    bid = settings().biz_bank_id
    out: dict[str, Any] = {"bank_id": bid}
    if force:
        docs = [d for d in await hindsight.list_documents(limit=300, bank_id=bid) if d.get("id")]
        out["deleted"] = await hindsight.delete_documents([d["id"] for d in docs], bank_id=bid)
    out["bank"] = await hindsight.ensure_bank(bid, mission=BIZ_MISSION,
                                             instructions=BIZ_RETAIN_INSTRUCTIONS,
                                             name="business decisions")
    out["seed"] = await hindsight.seed(bizcorpus.corpus(), bank_id=bid,
                                       context="business decision record")
    out["ledger"] = await bizledger.seed_ledger(bid)
    out["consolidate"] = await hindsight.recover_consolidation(bid)
    out["observations"] = await hindsight.wait_for_observations(bank_id=bid)
    out["stats_after"] = await hindsight.agent_stats(bid)
    DATA_DIR.mkdir(exist_ok=True)
    gt = bizcorpus.ground_truth()
    (DATA_DIR / "biz_ground_truth.json").write_text(json.dumps(gt, indent=1))
    out["ground_truth_totals"] = gt["totals"]
    return out


@app.post("/api/biz/consolidate")
async def biz_consolidate(wait: bool = Query(True)) -> dict[str, Any]:
    bid = settings().biz_bank_id
    rec = await hindsight.recover_consolidation(bid)
    waited = await hindsight.wait_for_observations(bank_id=bid) if wait else None
    return {"recover": rec, "observations": waited, "stats": await hindsight.agent_stats(bid)}


@app.get("/api/biz/ground-truth")
async def biz_gt() -> dict[str, Any]:
    p = DATA_DIR / "biz_ground_truth.json"
    return json.loads(p.read_text()) if p.exists() else bizcorpus.ground_truth()


@app.post("/api/health/llm")
async def health_llm() -> dict[str, Any]:
    """Explicit, because on Cloud it costs a tiny LLM call."""
    return await hindsight.health_check_llm()
