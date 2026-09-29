"""Per-IP rate limiting, and the admin surface that must not exist in production.

Two concerns, deliberately in one place so neither can be forgotten by a handler:

1. **Expensive and shared-state endpoints are admin-only.** Seeding costs 72 paid extractions, consolidation
   is a paid Hindsight operation, and `commit`/`resolve` write to the shared decision bank. Left open, any
   stranger can spend your money and, worse, pollute the memory the product cites. In production these are
   not merely forbidden, they do not exist: the middleware 404s them, the same answer an unknown path gives,
   so nothing is advertised.

2. **The remaining prompt endpoints are limited per IP.** The product has no accounts, so the only
   available identity is the client address. The limit exists to stop a loop, not to meter a real user.

Trusting the client address: the api container is reachable only through Traefik, so `request.client.host` is
Traefik's own address, not the visitor's. The real address arrives in `X-Forwarded-For`, and Traefik
**appends** to whatever the client sent, so the **last** entry is the one our own proxy observed. Taking the
last entry is what makes this header trustworthy; a client-supplied prefix cannot displace it. Taking the
first would be trivially spoofable, which is the usual way this is got wrong.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("premortem.ratelimit")

# Paths that cost real money or mutate the shared knowledge base. Exact paths, plus the legacy deploy
# surface from the abandoned pivot, which has the same shape of hazard.
ADMIN_PATHS: frozenset[str] = frozenset({
    "/api/biz/seed",
    "/api/biz/consolidate",
    "/api/seed",
    "/api/consolidate",
    "/api/replay",
    "/api/health/llm",
})

# The paths a visitor may call, and therefore the ones that count against the limit. Deliberately a list
# rather than "everything except": reading the presets, the history or health must stay free, or a single
# page load would exhaust a visitor's allowance before they typed anything.
COUNTED_PATHS: frozenset[str] = frozenset({
    "/api/biz/redflag",
    "/api/biz/redflag/stream",
    "/api/biz/history/draft",
    "/api/biz/history/commit",
    "/api/biz/history/resolve",
    "/api/assess",
})


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        log.warning("%s is not an integer; falling back to %s", name, default)
        return default


@dataclass
class _Window:
    count: int = 0
    reset_at: float = 0.0


@dataclass
class RateLimiter:
    """Fixed-window counter per client address.

    Fixed window rather than sliding: the failure mode at a boundary is a visitor getting up to 2x the
    limit for one window, which is acceptable for an abuse guard and costs one float comparison instead of
    a list of timestamps per IP. Memory stays bounded because expired windows are pruned.
    """

    limit: int = field(default_factory=lambda: _env_int("RATE_LIMIT_REQUESTS", 10))
    window_s: int = field(default_factory=lambda: _env_int("RATE_LIMIT_WINDOW_SECONDS", 86400))
    _windows: dict[str, _Window] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last_prune: float = 0.0

    def check(self, ip: str) -> tuple[bool, int, int]:
        """Consume one unit. Returns (allowed, remaining, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            self._maybe_prune(now)
            w = self._windows.get(ip)
            if w is None or now >= w.reset_at:
                w = _Window(count=0, reset_at=now + self.window_s)
                self._windows[ip] = w
            if w.count >= self.limit:
                return False, 0, max(1, int(w.reset_at - now))
            w.count += 1
            return True, max(0, self.limit - w.count), max(1, int(w.reset_at - now))

    def peek(self, ip: str) -> tuple[int, int]:
        """(used, retry_after) without consuming. For reporting, not for gating."""
        now = time.time()
        with self._lock:
            w = self._windows.get(ip)
            if w is None or now >= w.reset_at:
                return 0, 0
            return w.count, max(0, int(w.reset_at - now))

    def reset(self, ip: str | None = None) -> None:
        with self._lock:
            if ip is None:
                self._windows.clear()
            else:
                self._windows.pop(ip, None)

    def _maybe_prune(self, now: float) -> None:
        # Cheap amortised cleanup: only sweep occasionally, and only when the map has grown. Without this a
        # public endpoint accumulates one entry per address forever.
        if len(self._windows) < 1000 or now - self._last_prune < 300:
            return
        dead = [k for k, v in self._windows.items() if now >= v.reset_at]
        for k in dead:
            self._windows.pop(k, None)
        self._last_prune = now


limiter = RateLimiter()


def client_ip(request: Any) -> str:
    """The visitor's address, from the header our own proxy appends to.

    See the module docstring: the LAST entry of `X-Forwarded-For` is the one Traefik observed and added
    itself. Falling back to `X-Real-IP`, then to the socket peer, keeps this working if the deployment shape
    changes.
    """
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    return getattr(getattr(request, "client", None), "host", None) or "unknown"


def app_mode() -> str:
    """`prod` or `dev`. The single switch for the whole guard surface.

    One variable rather than several, because the dangerous combination is getting it half right: someone
    enables the admin endpoints in production to seed once and forgets to turn the rate limit back on, or the
    reverse. `APP_MODE` makes the safe posture the default and the unsafe posture one obvious deliberate act.

    Unrecognised values resolve to `prod`, so a typo tightens the system rather than opening it. That is the
    failure direction a security switch should have.
    """
    mode = str(os.getenv("APP_MODE", "prod")).strip().lower()
    return mode if mode in ("prod", "dev") else "prod"


def is_dev() -> bool:
    return app_mode() == "dev"


def _flag(name: str, *, if_unset: str) -> bool:
    """An explicit env var wins; otherwise fall back to the mode's default."""
    raw = os.getenv(name)
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    return str(if_unset).lower() in ("1", "true", "yes", "on")


def admin_enabled() -> bool:
    """Whether the money-spending endpoints exist at all.

    On in dev, off in prod. Production is already seeded, so there is no reason for a request that spends 72
    paid extractions to be reachable by anyone who has the URL.
    """
    return _flag("ADMIN_ENDPOINTS_ENABLED", if_unset="1" if is_dev() else "0")


def limit_enabled() -> bool:
    """Whether the per-visitor cap applies. Off in dev, so development is never spent fighting it."""
    return _flag("RATE_LIMIT_ENABLED", if_unset="0" if is_dev() else "1")


def payment_required_body(used: int, limit: int, retry_after: int) -> dict[str, Any]:
    """The body the frontend keys off. `contact_sales` is the signal to open the gate rather than retry."""
    return {
        "error": "rate_limited",
        "reason": "contact_sales",
        "message": (
            f"You have used all {limit} free reviews for now. Get in touch to keep going."
        ),
        "limit": limit,
        "used": used,
        "retry_after_seconds": retry_after,
    }
