"""OpenCode Go chat client (async).

Verified behaviour (docs/MODELS.md section 1):
 - chat REQUIRES an `x-opencode-session` header; without it the request fails with MissingSessionID
 - `response_format: {"type":"json_object"}` works
 - `tool_choice: "auto"` and forced tool calling both work
Retry ladder: primary model -> one repair attempt -> fallback model. Never retries a network call blindly.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from .config import settings

log = logging.getLogger("premortem.llm")

# models that failed hard this process; never retried again
_DEAD: set[str] = set()


def _extract_json(text: str) -> dict[str, Any] | None:
    """LLMs sometimes wrap JSON in prose or fences. Take the outermost object."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


async def chat_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """One JSON-mode completion. Returns (parsed_or_none, meta). Never raises for API errors."""
    s = settings()
    meta: dict[str, Any] = {"model": model or s.llm_model, "llm_calls": 0, "fallback_used": False}
    if not s.llm_key:
        return None, {**meta, "error": "OPENCODE_GO_API_KEY not set"}

    order = [model or s.llm_model]
    # The fallback lane (9Router gareebi) has been observed returning "Model is unavailable".
    # Only try it if it has not already failed in this process, so a dead fallback cannot double latency.
    if s.llm_fallback_model and s.llm_fallback_model != order[0] and s.llm_fallback_model not in _DEAD:
        order.append(s.llm_fallback_model)

    last_err = ""
    async with httpx.AsyncClient(timeout=120.0) as hx:
        for i, m in enumerate(order):
            body = {
                "model": m,
                "stream": False,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            }
            try:
                r = await hx.post(
                    f"{s.llm_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {s.llm_key}",
                        "Content-Type": "application/json",
                        "x-opencode-session": s.opencode_session,
                    },
                    json=body,
                )
                meta["llm_calls"] += 1
                if r.status_code >= 400:
                    last_err = f"HTTP {r.status_code}: {r.text[:180]}"
                    if r.status_code in (400, 401, 403):
                        _DEAD.add(m)  # config/availability problem, not transient
                    log.warning("llm %s failed: %s", m, last_err)
                    continue
                data = r.json()
                if isinstance(data, dict) and data.get("error"):
                    last_err = str(data["error"])[:180]
                    continue
                msg = (data.get("choices") or [{}])[0].get("message") or {}
                # deepseek models return a `reasoning_content` side channel. With a small max_tokens the
                # whole budget can be spent on reasoning and `content` comes back empty, so fall back to it.
                body_text = (msg.get("content") or "").strip() or (msg.get("reasoning_content") or "").strip()
                parsed = _extract_json(body_text)
                if parsed is not None:
                    meta["model"] = m
                    meta["fallback_used"] = i > 0
                    return parsed, meta
                last_err = "model returned no parsable JSON"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"
                log.warning("llm %s exception: %s", m, last_err)
    return None, {**meta, "error": last_err}


async def chat_text(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 500,
    history: list[dict[str, str]] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Plain-text completion, used for the MEMORY=off baseline."""
    s = settings()
    meta: dict[str, Any] = {"model": model or s.llm_model, "llm_calls": 0}
    if not s.llm_key:
        return None, {**meta, "error": "OPENCODE_GO_API_KEY not set"}
    body = {
        "model": model or s.llm_model,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": (
            [{"role": "system", "content": system}]
            + [
                {"role": str(m.get("role")), "content": str(m.get("content", ""))}
                for m in (history or [])
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
            + [{"role": "user", "content": user}]
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as hx:
            r = await hx.post(
                f"{s.llm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {s.llm_key}",
                    "Content-Type": "application/json",
                    "x-opencode-session": s.opencode_session,
                },
                json=body,
            )
            meta["llm_calls"] += 1
            if r.status_code >= 400:
                return None, {**meta, "error": f"HTTP {r.status_code}: {r.text[:180]}"}
            data = r.json()
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            text = (msg.get("content") or "").strip() or (msg.get("reasoning_content") or "").strip()
            if not text:
                return None, {**meta, "error": "model returned empty content (token budget spent on reasoning)"}
            return text, meta
    except Exception as e:  # noqa: BLE001
        return None, {**meta, "error": f"{type(e).__name__}: {e}"}


async def chat_stream(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 3000,
    reasoning: bool = False,
    history: list[dict[str, str]] | None = None,
):
    """Async generator of (kind, text) pairs, where kind is "content" or "reasoning".

    Callers must unpack: `async for kind, piece in chat_stream(...)`. Tuple-shaped rather than two separate
    generators so a single upstream stream feeds both lanes in order.

    Verified on OpenCode Go: the SSE stream emits `reasoning_content` deltas BEFORE `content`.
    With `reasoning=True` the caller also receives ("reasoning", text) pairs, which the UI renders as a
    collapsed "thinking" trace. Those are not shown unless asked for, but they are a real reasoning trace
    the model already produces, so discarding them is throwing away signal. The raw stream looks like:

        data: {"choices":[{"delta":{"role":"assistant","content":"","reasoning_content":"We"}}]}
        ...
        data: {"choices":[{"delta":{"content":"Not as described"}}]}
        data: [DONE]
    """
    s = settings()
    if not s.llm_key:
        yield ("content", "[no OPENCODE_GO_API_KEY configured]")
        return
    body = {
        "model": model or s.llm_model,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": (
            [{"role": "system", "content": system}]
            + [
                {"role": str(m.get("role")), "content": str(m.get("content", ""))}
                for m in (history or [])
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
            + [{"role": "user", "content": user}]
        ),
    }
    headers = {
        "Authorization": f"Bearer {s.llm_key}",
        "Content-Type": "application/json",
        "x-opencode-session": s.opencode_session,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as hx:
            async with hx.stream("POST", f"{s.llm_base_url}/chat/completions",
                                 headers=headers, json=body) as r:
                if r.status_code >= 400:
                    detail = (await r.aread()).decode()[:200]
                    yield ("content", f"[upstream error {r.status_code}: {detail}]")
                    return
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except Exception:  # noqa: BLE001
                        continue
                    delta = ((chunk.get("choices") or [{}])[0].get("delta") or {})
                    if reasoning:
                        # Same stream, separate lane: yield the model's thinking as its own event so the
                        # UI can show it collapsed. Previously discarded, which threw away a genuine
                        # reasoning trace the model was already producing for free.
                        think = delta.get("reasoning_content")
                        if think:
                            yield ("reasoning", think)
                    # content only for the answer lane: reasoning_content is the thinking, not the answer
                    piece = delta.get("content")
                    if piece:
                        yield ("content", piece)
    except Exception as e:  # noqa: BLE001
        yield ("content", f"[stream failed: {type(e).__name__}: {e}]")
