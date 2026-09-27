"""Config + the Hindsight client factory.

Verified facts this file encodes (see docs/MODELS.md section 9):
 - `banks.*` methods are async; `retain`/`recall`/`reflect` are sync wrappers. We use the `a*` async
   variants so nothing touches the event loop FastAPI owns.
 - Never call `asyncio.run()` around client methods: the client's own sync wrapper uses
   `asyncio.get_event_loop()` and closing that loop breaks every later call.
 - `recall` uses no LLM (free). `retain` and `reflect` cost tokens.
"""
from __future__ import annotations

import os
from functools import lru_cache

from hindsight_client import Hindsight

BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "premortem")


def _clean_url(url: str) -> str:
    return url.rstrip("/")


class Settings:
    def __init__(self) -> None:
        self.hindsight_url = _clean_url(os.getenv("HINDSIGHT_API_URL", "https://api.hindsight.vectorize.io"))
        self.hindsight_key = os.getenv("HINDSIGHT_API_KEY", "")
        self.bank_id = BANK_ID
        self.llm_base_url = _clean_url(os.getenv("OPENCODE_GO_BASE_URL", "https://opencode.ai/zen/go/v1"))
        self.llm_key = os.getenv("OPENCODE_GO_API_KEY", "")
        self.llm_model = os.getenv("LLM_MODEL", "deepseek-v4.1-flash")
        self.llm_fallback_model = os.getenv("LLM_FALLBACK_MODEL", "")
        self.opencode_session = os.getenv("OPENCODE_SESSION", "pre-mortem-local")
        self.min_proof = int(os.getenv("MIN_PROOF", "1"))
        self.cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

    def problems(self) -> list[str]:
        """Missing config, reported by /health. Never raises, so `next build` and imports stay safe."""
        p = []
        if not self.hindsight_key:
            p.append("HINDSIGHT_API_KEY is not set")
        if not self.llm_key:
            p.append("OPENCODE_GO_API_KEY is not set")
        if self.min_proof < 1:
            p.append("MIN_PROOF must be >= 1")
        return p


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def client() -> Hindsight:
    s = settings()
    # max_attempts=1: a failed paid call must not silently retry.
    return Hindsight(
        base_url=s.hindsight_url,
        api_key=s.hindsight_key,
        timeout=float(os.getenv("HINDSIGHT_TIMEOUT", "180")),
        max_attempts=1,
    )
