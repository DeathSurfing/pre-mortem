"""Laya integration: local System One decisions that replace an LLM classification call.

Why this is here: classifying a free-text business decision into (domain, decision_type) used to cost one
LLM call per request. Laya does the same job locally, offline, in ~1.4s, for zero marginal cost, and
returns calibrated probabilities instead of prose we would have to parse.

Verified on 2026-09-27 in this repo (ONNX int4, CPU):
    LOAD 9.1s   PREDICT 1.39s
    domain -> "pricing" p=0.9949 confidence=0.9793   (correct for the discount prompt)
    reversibility -> score 0.7567, most likely "Moderate"
    gives_value_without_commitment -> noul 0.3875

Three Laya question types map onto things this app already needs:
    choice -> domain, decision_type
    score  -> reversibility, and how much value is being given away
    noul   -> boolean flags that feed the risk verdict

Fallback discipline: if Laya is unavailable (missing model, no onnxruntime, OOM), `classify()` falls back
to the LLM path so the product still works. The verdict is never produced by Laya; it stays deterministic.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger("premortem.laya")

# Smaller of the published builds; int8 is 582MB and the container cgroup is 4GB.
_DEFAULT_REPO = os.getenv("LAYA_REPO", "techtheist/laya-onnx")
_DEFAULT_SUBFOLDER = os.getenv("LAYA_SUBFOLDER", "en")
_DEFAULT_ONNX = os.getenv("LAYA_ONNX_FILE", "model_int4.onnx")
_LAYA_ENABLED = os.getenv("LAYA_ENABLED", "1") not in ("0", "false", "False")

DOMAIN_OPTIONS = {
    "pricing": "price, discount, packaging or commercial terms",
    "hiring": "recruiting, headcount or a person's role",
    "vendor": "a third party supplier, tool or service",
    "marketing": "advertising, demand generation or channel spend",
    "launch": "releasing a product or feature to customers",
    "buildvsbuy": "building something in house or purchasing it",
    "expansion": "a new market, region or office",
    "operations": "internal process, tooling or delivery",
    "finance": "budget, cash or accounting treatment",
    "legal": "contract, regulatory or compliance exposure",
}

_agent = None
_lock = threading.Lock()
_load_error: str | None = None


def available() -> bool:
    return _LAYA_ENABLED


def _load():
    """Load once, lazily. Never raises: a failure here degrades to the LLM path."""
    global _agent, _load_error
    if _agent is not None or _load_error is not None:
        return _agent
    with _lock:
        if _agent is not None or _load_error is not None:
            return _agent
        if not _LAYA_ENABLED:
            _load_error = "LAYA_ENABLED=0"
            return None
        try:
            from huggingface_hub import snapshot_download
            from laya.onnx_agent import ONNXAgent

            local = os.getenv("LAYA_LOCAL_DIR") or snapshot_download(
                _DEFAULT_REPO, allow_patterns=[f"{_DEFAULT_SUBFOLDER}/*"])
            model_dir = os.path.join(local, _DEFAULT_SUBFOLDER) if os.path.isdir(
                os.path.join(local, _DEFAULT_SUBFOLDER)) else local
            onnx_path = os.path.join(model_dir, _DEFAULT_ONNX)
            t0 = time.time()
            _agent = ONNXAgent(model_dir, onnx_path=onnx_path)
            log.info("laya loaded from %s in %.1fs", model_dir, time.time() - t0)
        except Exception as e:  # noqa: BLE001
            _load_error = f"{type(e).__name__}: {e}"
            log.warning("laya unavailable, falling back to the LLM classifier: %s", _load_error)
            return None
    return _agent


def status() -> dict[str, Any]:
    return {
        "enabled": _LAYA_ENABLED,
        "loaded": _agent is not None,
        "error": _load_error,
        "repo": _DEFAULT_REPO,
        "onnx_file": _DEFAULT_ONNX,
        "question_types": ["choice", "score", "noul"],
    }


def classify_sync(text: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Blocking classify. Returns (attrs, meta). attrs is None when Laya cannot answer."""
    a = _load()
    if a is None:
        return None, {"engine": "laya", "ok": False, "error": _load_error}

    questions = {
        "domain": {
            "type": "choice",
            "instructions": "Which business area is the decision in `state` about?",
            "criteria": DOMAIN_OPTIONS,
        },
        "reversibility": {
            "type": "score",
            "instructions": "How hard would it be to undo this decision once made?",
            "criteria": ["Easy", "Moderate", "Hard"],
        },
        "gives_value_without_commitment": {
            "type": "noul",
            "instructions": "The decision gives away value or margin without asking for anything in return",
        },
        "is_high_blast_radius": {
            "type": "noul",
            "instructions": "The decision affects customers or many people at once, not just an internal team",
        },
    }
    try:
        t0 = time.time()
        out = a.system_one(text, questions)
        dt = time.time() - t0
    except Exception as e:  # noqa: BLE001
        return None, {"engine": "laya", "ok": False, "error": f"{type(e).__name__}: {e}"}

    ans = (out or {}).get("answers") or {}
    dom = ans.get("domain") or {}
    rev = ans.get("reversibility") or {}
    value = ans.get("gives_value_without_commitment") or {}
    blast = ans.get("is_high_blast_radius") or {}

    domain = dom.get("choice") if dom.get("type") == "choice" else None
    if domain not in DOMAIN_OPTIONS:
        domain = "operations"

    attrs = {
        "domain": domain,
        "decision_type": "unspecified",   # Laya gives the area; the specific mechanics still need a read
        "intent": text[:300],
        "rationale": "",
        "keywords": [],
        "laya": {
            "domain_probability": round(float(dom.get("probabilities", {}).get(domain, 0.0)), 4)
            if dom.get("probabilities") else None,
            "domain_confidence": round(float(dom.get("confidence") or 0.0), 4),
            "reversibility_score": round(float(rev.get("score") or 0.0), 4) if rev.get("type") == "score" else None,
            "reversibility_label": (rev.get("legend") or {}).get(
                str(max((rev.get("probabilities") or {"0": 0}), key=lambda k: (rev.get("probabilities") or {})[k]))
            ) if rev.get("probabilities") else None,
            "gives_value_without_commitment": round(float(value.get("noul") or 0.0), 4),
            "is_high_blast_radius": round(float(blast.get("noul") or 0.0), 4),
        },
    }
    return attrs, {"engine": "laya", "ok": True, "seconds": round(dt, 2), "model": (out or {}).get("model")}


async def classify_async(text: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Async wrapper: Laya inference is CPU-bound, so run it off the event loop."""
    import asyncio
    return await asyncio.to_thread(classify_sync, text)
