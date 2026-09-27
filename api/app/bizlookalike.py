"""Business decision red-flagger.

Flow, and why it is shaped this way:

    free-text prompt
        -> one LLM call extracts {domain, decision_type, what they intend, the rationale}
        -> recall (NO LLM) against the business bank
        -> deterministic rank + verdict (domain + decision_type filter, proof counts)
        -> one LLM call writes the opinion and names the differing detail
        -> ledger boosts any class that has burned us before

The verdict itself is never an LLM opinion: it comes from the outcomes of recalled precedents. The model
only classifies the prompt and writes prose. That separation is what makes the numbers defensible.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import bizcorpus, hindsight, laya_client
from .bizcorpus import Prompt
from .config import settings
from .llm import chat_json, chat_stream, chat_text
from .rank import rank, verdict

DOMAINS = ["pricing", "hiring", "vendor", "marketing", "launch", "buildvsbuy", "expansion", "operations", "finance", "legal"]

CLASSIFY_SCHEMA = {
    "type": "object",
    "required": ["domain", "decision_type", "intent"],
    "properties": {
        "domain": {"type": "string", "description": f"one of: {', '.join(DOMAINS)}"},
        "decision_type": {
            "type": "string",
            "description": "short kebab-case label, e.g. discount, senior-hire, vendor-switch, budget-shift, build, buy, feature-ga, price-increase, new-office",
        },
        "intent": {"type": "string", "description": "one sentence, what the person intends to do"},
        "rationale": {"type": "string", "description": "the reason they gave, if any"},
        "keywords": {"type": "array", "items": {"type": "string"}, "description": "up to 6 search terms"},
    },
}

CLASSIFY_SYSTEM = (
    "You classify a business decision someone is considering, so it can be matched against the company's "
    "own past decisions.\n"
    f"Choose `domain` from this list only: {', '.join(DOMAINS)}.\n"
    "Give `decision_type` as a short kebab-case label describing the mechanics of the decision "
    "(discount, senior-hire, vendor-switch, budget-shift, build, buy, feature-ga, price-increase, "
    "new-office, and so on).\n"
    "Do not give an opinion, a risk assessment, or advice. Classify only. Return JSON."
)

OPINION_SCHEMA = {
    "type": "object",
    "required": ["headline", "why"],
    "properties": {
        "headline": {"type": "string", "description": "one sentence verdict, plain business language"},
        "why": {"type": "string", "description": "2-4 sentences citing the recalled decisions and their results"},
        "differentiating_detail": {
            "type": "string",
            "description": "the ONE detail that differed between a past decision that went badly and a near-identical one that went fine; empty if none applies",
        },
        "suggested_guardrail": {
            "type": "string",
            "description": "the specific condition that would make this decision safe, taken from the recorded lessons; empty if none",
        },
        "open_questions": {"type": "array", "items": {"type": "string"}, "description": "up to 3 things the person should confirm before deciding"},
    },
}

STREAM_OPINION_SYSTEM = (
    "You are a business decision reviewer inside a company. You are given a decision the user is "
    "considering and the company's OWN recalled past decisions in the same domain.\n"
    "Write your review in EXACTLY this plain-text format, with these five labels and nothing else. "
    "Do not use JSON, braces, or code fences.\n"
    "HEADLINE: one sentence verdict in plain business language\n"
    "WHY: 2-4 sentences of reasoning\n"
    "DIFFERENCE: the one detail that differed between a past decision that went badly and a "
    "near-identical one that went fine, or NONE if no such pair exists\n"
    "GUARDRAIL: the specific condition that would make this safe, taken from the recorded lessons, "
    "or NONE\n"
    "QUESTIONS: up to 3 things to confirm first, one per line prefixed with '- ', or NONE\n"
    "Rules, in order of importance:\n"
    "1. EVERY claim must cite the decision id it comes from, inline, in the sentence. Write it like "
    "'we lost 6.2 points of margin when we did this in D-2025-0002'. A sentence with no id is a sentence "
    "you must not write.\n"
    "2. Base everything on the recalled decisions. Never invent a precedent, a number, or a result.\n"
    "3. Quote the actual figure or phrase from the record where it matters, not a paraphrase of it.\n"
    "4. Be direct and specific. This is a colleague flagging a real risk, not a consultant.\n"
    "5. If the recalled decisions do not cover this situation, say so plainly instead of stretching.\n"
    "6. Never claim to know something the recalled records do not state.\n"
    "Start your answer with HEADLINE: and follow the format exactly."
)

BASELINE_SYSTEM = (
    "You are reviewing a business decision. No company history is available to you. "
    "Give a short opinion in three bullets."
)


def query_for(p: Prompt) -> str:
    return p.text


def _block(precedents: list[dict[str, Any]]) -> str:
    lines = []
    for p in precedents[:6]:
        facts = p.get("all_texts") or ([p.get("text")] if p.get("text") else [])
        body = "\n".join(f"      - {f}" for f in facts if f)
        lines.append(
            f"- {p['launch_id']} ({p['date']}, {p['service']} / {p['change_class']}, "
            f"outcome={p['outcome']}, evidence={p['proof_count']}"
            f"{', near-identical decision that went FINE' if p.get('is_mirror') else ''}):\n{body}"
        )
    return "\n".join(lines)


async def classify(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Free text -> attributes.

    Laya first: it is local, offline, ~2s, and returns calibrated probabilities for `domain` plus two
    signals the LLM path never gave us (reversibility, whether value is being given away for nothing).
    The LLM is then used only for the things Laya cannot do: the specific kebab-case `decision_type`
    and the stated rationale. If Laya is unavailable the LLM does the whole job as before.
    """
    laya_attrs, laya_meta = await laya_client.classify_async(text)

    parsed, meta = await chat_json(CLASSIFY_SYSTEM, f"Decision under consideration:\n{text}", max_tokens=3000)
    calls = meta.get("llm_calls", 0)

    if not parsed:
        # no LLM either: fall back to whatever Laya gave us, which is still a real domain
        base = laya_attrs or {"domain": "operations", "decision_type": "unspecified",
                              "intent": text[:200], "rationale": "", "keywords": []}
        return base, {"llm_calls": calls, "laya": laya_meta, "degraded": True}

    if parsed.get("domain") not in DOMAINS:
        parsed["domain"] = "operations"
    # Laya's domain is a calibrated choice; trust it over the LLM when Laya answered confidently
    if laya_attrs and (laya_attrs.get("laya") or {}).get("domain_confidence", 0) >= 0.5:
        parsed["domain"] = laya_attrs["domain"]
    if laya_attrs:
        parsed["laya"] = laya_attrs.get("laya")
    return parsed, {"llm_calls": calls, "laya": laya_meta}


async def redflag(text: str, *, memory: bool = True, promoted: set[str] | None = None,
                  seed: str | None = None) -> dict[str, Any]:
    """Assess a free-text business decision. `seed` is an optional known domain/type for tests."""
    s = settings()
    now = datetime.now(timezone.utc)
    out: dict[str, Any] = {
        "memory": memory,
        "prompt": text,
        "precedents": [],
        "declined": [],
        "opinion": None,
        "engine": {"ranker": "deterministic", "llm": s.llm_model, "llm_calls": 0},
    }

    if seed:
        attrs = {"domain": seed.split(":")[0], "decision_type": seed.split(":")[1],
                 "intent": text[:200], "rationale": "", "keywords": []}
        out["engine"]["classified_by"] = "seed"
    else:
        attrs, cmeta = await classify(text)
        out["engine"]["llm_calls"] += cmeta.get("llm_calls", 0)
        out["engine"]["classified_by"] = cmeta.get("model")
    out["classified"] = attrs
    domain, dtype = attrs.get("domain"), attrs.get("decision_type")

    recalled: list[dict[str, Any]] = []
    if memory:
        q = " ".join([attrs.get("intent") or "", attrs.get("rationale") or "",
                      " ".join(attrs.get("keywords") or []), text])[:1200]
        recalled = await hindsight.recall(q, budget="mid", max_tokens=1800, bank_id=s.biz_bank_id)

    ranked = rank(recalled, now=now, promoted=promoted, service=domain, change_class=dtype,
                  min_proof=s.min_proof)
    if not ranked:
        # second attempt on domain alone, so a slightly different wording still finds its domain
        ranked = rank(recalled, now=now, promoted=promoted, service=domain, change_class=None,
                      min_proof=s.min_proof)
        if ranked:
            out["engine"]["match_relaxed"] = "matched on domain, decision_type differed"
    out["precedents"] = ranked[:6]

    all_ranked = rank(recalled, now=now, promoted=promoted, service=None, change_class=None, min_proof=0)
    seen = {p["launch_id"] for p in out["precedents"]}
    declined = []
    for d in all_ranked:
        if d["launch_id"] in seen or not d["launch_id"]:
            continue
        declined.append({
            "launch_id": d["launch_id"],
            "domain": d["service"],
            "decision_type": d["change_class"],
            "reason": (f"same area ({d['service']}) but a different kind of decision ({d['change_class']})"
                       if d["service"] == domain else
                       f"different area ({d['service']} / {d['change_class']})"),
            "proof_count": d["proof_count"],
        })
        if len(declined) >= 3:
            break
    out["declined"] = declined

    v = verdict(out["precedents"], service=domain, change_class=dtype)
    out.update({"risk": v["risk"], "confidence": v["confidence"],
                "no_precedent": v["no_precedent"], "verdict_rules": v["rules"],
                "conflicting": v.get("conflicting", 0), "mirrors": v.get("mirrors", 0)})

    if not memory:
        txt, meta = await chat_text(BASELINE_SYSTEM, text, max_tokens=3000)
        out["baseline"] = txt
        out["engine"]["llm_calls"] += meta.get("llm_calls", 0)
        return out

    if v["no_precedent"]:
        out["no_precedent_message"] = (
            "No past decision in this company covers this. I am not going to invent a precedent. "
            f"{len(out['declined'])} neighbouring decisions were considered and declined."
        )
        out["facts_used"] = []
        return out

    user = (
        f"DECISION THE USER IS CONSIDERING\n{text}\n\n"
        f"CLASSIFIED AS: domain={domain}, type={dtype}\n"
        f"THEIR STATED RATIONALE: {attrs.get('rationale') or '(none given)'}\n\n"
        f"THE COMPANY'S OWN RECALLED PAST DECISIONS\n{_block(out['precedents'])}\n\n"
        "Write the review. Return JSON with headline, why, differentiating_detail, "
        "suggested_guardrail, open_questions."
    )
    parsed, ometa = await chat_json(OPINION_SYSTEM, user, max_tokens=3000)
    out["engine"]["llm_calls"] += ometa.get("llm_calls", 0)
    out["engine"]["model_used"] = ometa.get("model")
    if ometa.get("error"):
        out["engine"]["llm_error"] = ometa["error"]
    if parsed:
        out["opinion"] = {
            "headline": parsed.get("headline"),
            "why": parsed.get("why"),
            "differentiating_detail": parsed.get("differentiating_detail") or None,
            "suggested_guardrail": parsed.get("suggested_guardrail") or None,
            "open_questions": parsed.get("open_questions") or [],
        }
    out["facts_used"] = sorted({p["launch_id"] for p in out["precedents"] if p["launch_id"]})
    out["engine"]["attribution_unverified"] = [
        p["launch_id"] for p in out["precedents"] if not p.get("attribution_ok", True)]
    prose = " ".join(str(v) for v in [
        (out.get("opinion") or {}).get("headline"),
        (out.get("opinion") or {}).get("why"),
        (out.get("opinion") or {}).get("differentiating_detail"),
        (out.get("opinion") or {}).get("suggested_guardrail"),
    ] if v)
    cited = sorted({f for f in out["facts_used"] if f and f in prose})
    out["engine"]["citations_in_prose"] = cited
    out["engine"]["uncited_facts"] = sorted(set(out["facts_used"]) - set(cited))
    if out["facts_used"] and not cited:
        out["engine"]["citation_warning"] = (
            "the prose cited none of the recalled decision ids; treat the card list as the source, not the summary"
        )
    return out


async def redflag_reflect(text: str, *, promoted: set[str] | None = None) -> dict[str, Any]:
    """Showcase path: let Hindsight answer it itself. Costs real tokens."""
    base = await redflag(text, memory=True, promoted=promoted)
    schema = {"type": "object", "required": ["headline"],
              "properties": {"headline": {"type": "string"}, "why": {"type": "string"},
                             "differentiating_detail": {"type": "string"}}}
    r = await hindsight.reflect(
        query=(f"A business decision is being considered: {text}. Using our own past decisions, "
               f"what went wrong when we did something similar, and what made it work when it did?"),
        response_schema=schema, budget="low")
    base["reflect"] = r
    base["engine"]["engine"] = "hindsight-reflect"
    return base


# ------------------------------------------------------------------ streaming red-flag

async def redflag_stream(text: str, *, promoted: set[str] | None = None):
    """SSE generator for the chat UI.

    Event sequence, so the frontend can render the reasoning as it happens rather than a spinner:
        status  -> classifying (Laya + LLM extract)
        classify-> domain, decision_type, laya signals, reversibility
        status  -> recalling precedents
        precedents -> the cited cards, with outcome and proof
        status  -> writing the review
        delta   -> answer text, streamed
        done    -> engine block (llm_calls, citations, unverified ids)
        error   -> anything that went wrong, with the partial answer preserved

    The verdict is computed before the prose, so the UI can show the risk banner while the text streams.
    """
    s = settings()
    now = datetime.now(timezone.utc)

    def ev(kind: str, **data) -> str:
        return "data: " + json.dumps({"type": kind, **data}, default=str) + "\n\n"

    try:
        yield ev("status", message="classifying the decision", step="classify")
        attrs, cmeta = await classify(text)
        domain, dtype = attrs.get("domain"), attrs.get("decision_type")
        yield ev("classify", domain=domain, decision_type=dtype,
                 intent=attrs.get("intent"), rationale=attrs.get("rationale"),
                 laya=attrs.get("laya"), llm_calls=cmeta.get("llm_calls", 0))

        yield ev("status", message="recalling past decisions", step="recall")
        q = " ".join([attrs.get("intent") or "", attrs.get("rationale") or "",
                      " ".join(attrs.get("keywords") or []), text])[:1200]
        recalled = await hindsight.recall(q, budget="mid", max_tokens=1800, bank_id=s.biz_bank_id)

        ranked = rank(recalled, now=now, promoted=promoted, service=domain, change_class=dtype,
                      min_proof=s.min_proof)
        relaxed = False
        if not ranked:
            ranked = rank(recalled, now=now, promoted=promoted, service=domain,
                          change_class=None, min_proof=s.min_proof)
            relaxed = bool(ranked)
        precs = ranked[:6]
        v = verdict(precs, service=domain, change_class=dtype)

        all_ranked = rank(recalled, now=now, promoted=promoted, service=None, change_class=None, min_proof=0)
        seen = {p["launch_id"] for p in precs}
        declined = []
        for d in all_ranked:
            if d["launch_id"] in seen or not d["launch_id"]:
                continue
            declined.append({"launch_id": d["launch_id"], "domain": d["service"],
                             "decision_type": d["change_class"], "proof_count": d["proof_count"],
                             "reason": (f"same area ({d['service']}), different kind of decision"
                                        if d["service"] == domain else
                                        f"different area ({d['service']} / {d['change_class']})")})
            if len(declined) >= 3:
                break

        yield ev("verdict", risk=v["risk"], confidence=v["confidence"],
                 no_precedent=v["no_precedent"], rules=v["rules"], relaxed=relaxed)
        yield ev("precedents", precedents=[
            {"launch_id": p["launch_id"], "date": p["date"], "domain": p["service"],
             "decision_type": p["change_class"], "outcome": p["outcome"], "is_mirror": p["is_mirror"],
             "proof_count": p["proof_count"], "attribution_ok": p.get("attribution_ok", True),
             "text": (p.get("text") or "")[:400]}
            for p in precs], declined=declined)

        if v["no_precedent"]:
            msg = ("No past decision in this company covers this. I am not going to invent a precedent. "
                   f"{len(declined)} neighbouring decisions were considered and declined.")
            for chunk in _chunks(msg):
                yield ev("delta", text=chunk)
            yield ev("done", engine={"ranker": "deterministic", "llm_calls": cmeta.get("llm_calls", 0),
                                     "no_precedent": True, "model": s.llm_model},
                     facts_used=[], citations_in_prose=[], attribution_unverified=[])
            return

        yield ev("status", message="writing the review", step="write")
        user = (
            f"DECISION THE USER IS CONSIDERING\n{text}\n\n"
            f"CLASSIFIED AS: domain={domain}, type={dtype}\n"
            f"THEIR STATED RATIONALE: {attrs.get('rationale') or '(none given)'}\n\n"
            f"THE COMPANY'S OWN RECALLED PAST DECISIONS\n{_block(precs)}\n\n"
            "Write the review in the HEADLINE/WHY/DIFFERENCE/GUARDRAIL/QUESTIONS format. "
            "Cite decision ids inline in every sentence."
        )
        buf = ""
        async for piece in chat_stream(STREAM_OPINION_SYSTEM, user, max_tokens=3000):
            buf += piece
            yield ev("delta", text=piece)

        op = parse_review(buf)
        facts = sorted({p["launch_id"] for p in precs if p["launch_id"]})
        prose = buf if not op else " ".join(str(x) for x in op.values() if x)
        cited = sorted({f for f in facts if f in prose})
        yield ev("done", opinion=op,
                 engine={"ranker": "deterministic", "llm_calls": cmeta.get("llm_calls", 0) + 1,
                         "model": s.llm_model, "streamed": True},
                 facts_used=facts, citations_in_prose=cited,
                 uncited_facts=sorted(set(facts) - set(cited)),
                 attribution_unverified=[p["launch_id"] for p in precs if not p.get("attribution_ok", True)])
    except Exception as e:  # noqa: BLE001
        yield ev("error", message=f"{type(e).__name__}: {e}")


def _chunks(s: str, n: int = 28):
    for i in range(0, len(s), n):
        yield s[i:i + n]


def parse_review(text: str) -> dict[str, Any]:
    """Parse the delimited review format. Tolerant: a missing section becomes None, never a crash."""
    import re as _re
    out: dict[str, Any] = {"headline": None, "why": None, "differentiating_detail": None,
                           "suggested_guardrail": None, "open_questions": []}
    t = (text or "").strip()
    if t.startswith("```"):
        t = _re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = _re.sub(r"\n?```$", "", t).strip()

    def section(label: str, following: tuple[str, ...]) -> str | None:
        stop = "|".join(f"^{n}:" for n in following) or "$^"
        m = _re.search(rf"^{label}:\s*(.*?)(?={stop}|\Z)", t, _re.S | _re.M | _re.I)
        if not m:
            return None
        val = m.group(1).strip()
        return None if (not val or val.upper().startswith("NONE")) else val

    out["headline"] = section("HEADLINE", ("WHY", "DIFFERENCE", "GUARDRAIL", "QUESTIONS"))
    out["why"] = section("WHY", ("DIFFERENCE", "GUARDRAIL", "QUESTIONS"))
    out["differentiating_detail"] = section("DIFFERENCE", ("GUARDRAIL", "QUESTIONS"))
    out["suggested_guardrail"] = section("GUARDRAIL", ("QUESTIONS",))
    qs = section("QUESTIONS", ())
    if qs:
        out["open_questions"] = [x.strip("-\u2022 ").strip() for x in qs.splitlines() if x.strip("-\u2022 ").strip()]
    # a headline is the minimum viable answer
    return out if out["headline"] else {"headline": t[:400] if t else None, "why": None,
                                        "differentiating_detail": None,
                                        "suggested_guardrail": None, "open_questions": []}
