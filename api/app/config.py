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
BIZ_BANK_ID = os.getenv("HINDSIGHT_BIZ_BANK_ID", "bizdecisions")


def _clean_url(url: str) -> str:
    return url.rstrip("/")


class Settings:
    def __init__(self) -> None:
        self.hindsight_url = _clean_url(os.getenv("HINDSIGHT_API_URL", "https://api.hindsight.vectorize.io"))
        self.hindsight_key = os.getenv("HINDSIGHT_API_KEY", "")
        self.bank_id = BANK_ID
        self.biz_bank_id = BIZ_BANK_ID
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


BIZ_MISSION = (
    "I am a business decision reviewer. I recall what this company's own past decisions actually did and I "
    "flag the ones that went wrong. I never assert a precedent without citing a decision id."
)

BIZ_DIRECTIVES = [
    "Never assert a precedent without citing a decision id.",
    "Never invent a number, a result, or a past decision.",
    "Always state how many past decisions support the view, including when it is zero.",
    "Never give legal, tax, or investment advice; flag when a decision needs a specialist instead.",
    "Never tell the user they must proceed; state the risk and the condition that would make it safe.",
]

BIZ_RETAIN_INSTRUCTIONS = (
    "This is a record of a business decision. Extract as separate facts: what was decided, the rationale "
    "given at the time, the measured result, and any lesson recorded. Preserve names, percentages, dates "
    "and decision ids exactly. Do not summarise away the specific detail that made the difference between "
    "a decision that worked and one that did not."
)


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
