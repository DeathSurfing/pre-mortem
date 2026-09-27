"""FastAPI surface. Owns every Hindsight call; the browser never talks to Hindsight directly."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import hindsight, ledger, lookalike, replay
from .config import settings
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


@app.post("/api/health/llm")
async def health_llm() -> dict[str, Any]:
    """Explicit, because on Cloud it costs a tiny LLM call."""
    return await hindsight.health_check_llm()
