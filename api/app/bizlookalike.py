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

import re

import json
from datetime import datetime, timezone
from typing import Any

from . import bizcorpus, hindsight, laya_client
from .bizcorpus import Prompt
from .config import settings
from .llm import chat_json, chat_stream, chat_text
from .rank import rank, verdict

DOMAINS = ["pricing", "hiring", "vendor", "marketing", "launch", "buildvsbuy", "expansion",
           "operations", "finance", "legal", "compliance", "security", "partnership", "ops"]

# The domains this company's history actually contains, derived from the corpus rather than hand-listed so
# the two can never drift apart. Used to arbitrate the domain between the two classifiers.
COVERED_DOMAINS = frozenset(d.domain for d in bizcorpus.corpus())

# Mode gate thresholds on Laya's domain_probability.
#
# Measured on this corpus: greetings and thanks 0.21-0.45, context-only statements about a decision
# 0.18-0.23, real decisions 0.93-0.99. So a high score is reliably a decision and a low score is reliably
# not one.
#
# The floor is very low (0.15) on purpose. A statement of context without a proposed action ("Acme's
# renewal is at risk and their champion wants a gesture") scores 0.18, while "thanks, that helps" scores
# 0.21 — the signal cannot separate those two, so the model must arbitrate rather than Laya guessing. Only
# messages Laya scores as emphatically empty skip the model entirely.
#
# The asymmetry still drives the design: a message that should have been reviewed and is answered
# conversationally silently withholds the whole product, whereas a conversational message that gets
# reviewed is merely noisy. So the band where Laya decides alone is kept tiny.
LAYA_MODE_DECISION = 0.60
LAYA_MODE_CHAT = 0.15

CLASSIFY_SCHEMA = {
    "type": "object",
    "required": ["domain", "decision_type", "intent"],
    "properties": {
        "domain": {"type": "string", "description": f"one of: {', '.join(DOMAINS)}"},
        "decision_type": {
            "type": "string",
            "description": "short kebab-case label, e.g. discount, senior-hire, vendor-switch, budget-shift, build, buy, feature-ga, price-increase, new-office, audit-finding, incident-response, reseller-agreement, datacenter-region",
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
    "new-office, audit-finding, incident-response, reseller-agreement, datacenter-region, and so on).\n"
    "Also decide `mode`:\n"
    "  \"decision\" if the message asks for a judgement or review of a specific business decision the sender "
    "is considering or has made (should we / is this a good idea / what do you think of this plan / review "
    "this proposal).\n"
    "  \"chat\" for everything else: greetings, thanks, questions about this tool or how it works, questions "
    "about what happened in the past, small talk, or a follow-up asking for more detail on an answer already "
    "given. When unsure prefer \"chat\": a chat reply is cheap, while treating a greeting as a decision "
    "produces a verdict the sender never asked for.\n"
    "Do not give an opinion, a risk assessment, or advice. Classify only. Return JSON with the keys "
    "`mode`, `domain`, `decision_type`, `intent`, and `rationale`."
)

# Mode gate thresholds on Laya's domain_probability.
#
# Measured on this corpus: greetings and thanks 0.21-0.45, context-only statements about a decision
# 0.18-0.23, real decisions 0.93-0.99. So a high score is reliably a decision and a low score is reliably
# not one.
#
# The floor is very low (0.15) on purpose. A statement of context without a proposed action ("Acme's
# renewal is at risk and their champion wants a gesture") scores 0.18, while "thanks, that helps" scores
# 0.21 — the signal cannot separate those two, so the model must arbitrate rather than Laya guessing. Only
# messages Laya scores as emphatically empty skip the model entirely.
#
# The asymmetry still drives the design: a message that should have been reviewed and is answered
# conversationally silently withholds the whole product, whereas a conversational message that gets
# reviewed is merely noisy. So the band where Laya decides alone is kept tiny.
LAYA_MODE_DECISION = 0.60
LAYA_MODE_CHAT = 0.15

# Documented shape of the classify response. NOT passed as a JSON schema: the gateway only supports
# `response_format: json_object`, so the fields are described in CLASSIFY_SYSTEM instead.
CLASSIFY_SCHEMA = {
    "type": "object",
    "required": ["mode"],
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["decision", "chat"],
            "description": (
                "`decision` if the message asks for a judgement or review of a specific business decision "
                "the sender is considering or has made (should we / is this a good idea / what do you think "
                "of this plan / review this). "
                "`chat` for everything else: greetings, questions about the product or how it works, "
                "questions about past decisions, small talk, or a follow-up that just asks for more detail "
                "on an answer already given. When in doubt prefer `chat`: a chat reply is cheap, whereas "
                "treating a greeting as a decision produces a verdict the sender never asked for."
            ),
        },
        "domain": {"type": "string"},
        "decision_type": {"type": "string", "description": "kebab-case; empty when mode is chat"},
        "intent": {"type": "string", "description": "one short sentence on what the sender wants"},
    },
}

# A plain conversational reply. No memory is consulted and no id may be cited, because a normal chat answer
# must never look like a reviewed decision.
FOLLOWUP_SYSTEM = (
    "You are the assistant inside pre-mortem. Earlier in this conversation the user put a business decision "
    "to you and you reviewed it against the company's recorded history; the exchange is in the message "
    "history.\n"
    "You are now answering a FOLLOW-UP about that review. Treat it as conversation: further reasoning, "
    "clarification, or reasoning about the trade-offs. Do NOT re-issue a full review, do not restate the "
    "verdict, and do not repeat the evidence list.\n"
    "Rules:\n"
    "1. Only cite a decision id that already appears in the reviewed answer above. Never invent one. If the "
    "follow-up needs data you were not given, say so and say what would settle it.\n"
    "2. Do not give a fresh risk rating. You may reason about the existing one.\n"
    "3. Answer in plain prose, 1-4 sentences unless more is clearly wanted. No headings, no bullet clusters.\n"
    "4. If the follow-up is really a new decision rather than a question about the last answer, review that "
    "new decision honestly instead of forcing it into the old context."
)

CHAT_SYSTEM = (
    "You are the assistant inside pre-mortem, a tool that reviews business decisions against a company's own "
    "recorded history.\n"
    "The message you are replying to is NOT a decision to review. Answer it as a normal, helpful assistant "
    "would: plain prose, direct, no headings, no bullet clusters, no verdict, no risk rating.\n"
    "Rules:\n"
    "1. Do NOT give a risk level, a verdict, or a recommendation about a decision. That is the decision path's "
    "job, and a chat reply must never impersonate it.\n"
    "2. Do NOT cite a decision id. You have not been shown the company's records, so any id would be "
    "fabricated. If the sender asks about past decisions, say you can look them up and ask them to put the "
    "decision to you as a question to review.\n"
    "3. Keep it short: 1-3 sentences unless the sender clearly wants more.\n"
    "4. If the message is a greeting or a question about the tool, answer it and, where it helps, note that "
    "they can describe a decision and you will check it against what the company has done before."
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

def _guess_block(parsed: dict[str, Any] | None, domain: str, dtype: str) -> dict[str, Any]:
    """Shape the no-precedent guess, and strip anything that looks like a fabricated citation.

    Defence in depth: the prompt forbids ids, but a model can still emit one, and a fabricated decision id
    inside a block labelled "guess" is exactly the failure this product exists to avoid. Scan for the id
    pattern and drop it rather than passing it through.
    """
    if not parsed:
        return {"available": False, "reason": "the model did not return a usable guess"}
    out = {
        "available": True,
        "verdict": str(parsed.get("verdict") or "").strip(),
        "guess": str(parsed.get("guess") or parsed.get("body") or "").strip(),
        "confidence": str(parsed.get("confidence") or "LOW").strip().upper(),
        "watch": parsed.get("watch") or [],
        "domain": domain,
        "decision_type": dtype,
    }
    if isinstance(out["watch"], str):
        out["watch"] = [w.strip("- ").strip() for w in out["watch"].splitlines() if w.strip()]
    # strip fabricated citations from every text field
    id_re = re.compile(r"\b[DLA]-\d{4}-\d{3,4}\b")
    if id_re.search(out["guess"]) or id_re.search(out["verdict"]):
        out["guess"] = id_re.sub("[unverifiable reference removed]", out["guess"])
        out["verdict"] = id_re.sub("[unverifiable reference removed]", out["verdict"])
        out["stripped_fabricated_ids"] = True
    if out["confidence"] not in ("LOW", "MEDIUM", "HIGH"):
        out["confidence"] = "LOW"
    # a no-precedent guess can never be high confidence and honest at the same time
    if out["confidence"] == "HIGH":
        out["confidence"] = "MEDIUM"
        out["confidence_capped"] = True
    return out


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

# Streaming variant of the guess prompt: delimited labels rather than JSON, because a JSON object streamed
# token by token renders as literal escape sequences in the UI. Parsed by _parse_guess_block below.
NO_PRECEDENT_GUESS_STREAM_SYSTEM = (
    "You are a business decision reviewer inside a company. The company has NO recorded precedent for this "
    "decision, and that has already been stated to the user.\n"
    "Your job is to add an explicitly-labelled guess, not a verdict. Write in EXACTLY this format with these "
    "four labels and nothing else. No JSON, no braces, no code fences, no headings.\n"
    "VERDICT: one sentence stating plainly that there is not enough company history to judge this.\n"
    "GUESS: 2-4 sentences of general best practice for this kind of decision, written as a guess. This is what "
    "a competent advisor would say with no knowledge of this company's history.\n"
    "WATCH: up to 3 risks or questions that would change the decision, one per line prefixed with '- '.\n"
    "CONFIDENCE: exactly one of LOW, MEDIUM, HIGH, meaning how much weight the guess deserves. It must be LOW "
    "unless this is genuinely textbook territory.\n"
    "Rules, in order of importance:\n"
    "1. This is a guess from general practice, NOT company memory. Never cite a decision id. You have not been "
    "shown the company's records, so any id you write would be fabricated. Writing one is a failure.\n"
    "2. Never invent a figure, a past event, or a company-specific fact.\n"
    "3. Do not pretend to certainty. The GUESS label and the CONFIDENCE level are how the user knows this is "
    "not grounded in their history.\n"
    "4. Be useful. A flat 'I cannot help' is a non-answer; give the honest general read.\n"
    "Start with VERDICT: and follow the format exactly."
)


def _parse_guess_block(text: str) -> dict[str, Any]:
    """Parse the delimited guess format back into the shape _guess_block produces.

    Delimited rather than JSON because the guess is streamed to the user token by token, and a JSON object
    rendered incrementally shows literal escapes. Tolerant by design: a missing label yields an empty field
    rather than an exception, since this parses a partially-written model response.
    """
    keys = ("VERDICT", "GUESS", "WATCH", "CONFIDENCE")
    fields: dict[str, list[str]] = {k: [] for k in keys}
    current: str | None = None
    for line in text.splitlines():
        m = re.match(r"^\s*(%s)\s*:\s*(.*)$" % "|".join(keys), line, re.I)
        if m:
            current = m.group(1).upper()
            rest = m.group(2).strip()
            if rest:
                fields[current].append(rest)
        elif current:
            fields[current].append(line.rstrip())

    watch = [w.strip("- ").strip() for w in fields["WATCH"] if w.strip()]
    conf = " ".join(fields["CONFIDENCE"]).strip().upper().split()
    return {
        "verdict": "\n".join(fields["VERDICT"]).strip(),
        "guess": "\n".join(fields["GUESS"]).strip(),
        "watch": watch,
        "confidence": conf[0] if conf else "LOW",
    }


# Used ONLY when the company has no precedent. The refusal is stated first and stays true; the guess is a
# separate, fenced block that is forbidden from citing memory, so a general-model opinion can never be
# mistaken for the company's own recorded experience. That separation is the whole point of the product.
NO_PRECEDENT_GUESS_SYSTEM = (
    "You are a business decision reviewer inside a company. The company has NO recorded precedent for "
    "this decision, and that has already been stated to the user.\n"
    "Your job is to add an explicitly-labelled guess, not a verdict.\n"
    "Reply with a single JSON object with exactly these keys and no others:\n"
    '  "verdict"    one sentence stating plainly that there is not enough company history to judge this.\n'
    '  "guess"      2-4 sentences of general best practice for this kind of decision, written as a guess. '
    "This is what a competent advisor would say with no knowledge of this company's history.\n"
    '  "watch"      an array of up to 3 short strings: risks or questions that would change the decision.\n'
    '  "confidence" exactly one of "LOW", "MEDIUM", "HIGH", meaning how much weight the guess deserves. '
    "It must be LOW unless this is genuinely textbook territory.\n"
    "Rules, in order of importance:\n"
    "1. This is a guess from general practice, NOT company memory. Never cite a decision id. You have not "
    "been shown the company's records, so any id you write would be fabricated. Writing one is a failure.\n"
    "2. Never invent a figure, a past event, or a company-specific fact.\n"
    "3. Do not pretend to certainty. The GUESS label and the CONFIDENCE level are how the user knows this "
    "is not grounded in their history.\n"
    "4. Be useful. A flat 'I cannot help' is a non-answer; give the honest general read.\n"
    'Output JSON only. Example shape: {"verdict": "...", "guess": "...", "watch": ["..."], "confidence": "LOW"}'
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

    # Same call, no extra cost: `mode` decides whether this is a decision to review or ordinary
    # conversation. Routing on the classification we were already paying for is why this is free.
    parsed, meta = await chat_json(CLASSIFY_SYSTEM, f"Message from the user:\n{text}", max_tokens=3000)
    calls = meta.get("llm_calls", 0)

    if not parsed:
        # no LLM either: fall back to whatever Laya gave us, which is still a real domain
        base = laya_attrs or {"domain": "operations", "decision_type": "unspecified",
                              "intent": text[:200], "rationale": "", "keywords": []}
        return base, {"llm_calls": calls, "laya": laya_meta, "degraded": True}

    # ---- mode gate: is this a decision to review, or ordinary conversation?
    #
    # Laya decides this, because its domain probability separates the two cleanly and it costs nothing.
    # Measured on this corpus (domain_probability):
    #     "hey, how are you doing today?"                0.29
    #     "what did we decide about the Acme renewal?"   0.27
    #     "what does this tool actually do?"             0.45
    #     "should I give Acme a 30% discount...?"        0.99
    #     "we are considering opening an office in..."   0.94
    # So: high means a real business-decision area, low means nothing decidable was said. The band in the
    # middle is genuinely ambiguous and falls back to the model's own `mode` field, which is the only part
    # of the classification that costs anything.
    mode = "decision"
    if laya_attrs:
        prob = ((laya_attrs.get("laya") or {}).get("domain_probability"))
        prob = float(prob) if isinstance(prob, (int, float)) else None
        if prob is not None:
            if prob >= LAYA_MODE_DECISION:
                mode = "decision"
            elif prob <= LAYA_MODE_CHAT:
                mode = "chat"
            else:
                mode = "chat" if str(parsed.get("mode", "")).strip().lower() == "chat" else "decision"
                parsed["mode_arbitration"] = f"laya ambiguous ({prob:.2f}), model decided"
    else:
        # no Laya available: the model's own field is all we have
        mode = "chat" if str(parsed.get("mode", "")).strip().lower() == "chat" else "decision"
    parsed["mode"] = mode
    if parsed.get("domain") not in DOMAINS:
        parsed["domain"] = "operations"
    # Trust Laya's domain over the LLM ONLY when Laya is actually sure. Measured on the audit prompt, Laya
    # returned `launch` at 0.5356 confidence (its nearest bucket, since its taxonomy has no compliance
    # label) and that overrode a correct LLM answer, recalling launch decisions for a compliance question.
    # 0.75 is above Laya's coin-flip band and below its real convictions (0.96-0.99 on clear prompts).
    # Domain arbitration. Both models classify, so this is a correctness decision, not a cost one.
    #
    # Laya has a fixed taxonomy with no bucket for compliance, security, or partnership, and on those
    # prompts it returns its nearest label with high confidence (measured: the audit prompt -> `launch` at
    # 0.825). A numeric trust threshold cannot separate that from a genuine conviction, because Laya is
    # genuinely convinced. The LLM, by contrast, is the only one told which domains this company's history
    # actually covers (COVERED_DOMAINS, derived from the corpus).
    #
    # So: prefer the LLM's domain when it names a covered area, fall back to Laya otherwise. Laya's value
    # in this app is its calibrated probability plus the reversibility and value-given-away signals, not
    # its domain label, so its label is reported but not authoritative.
    laya_dom_conf = ((laya_attrs or {}).get("laya") or {}).get("domain_confidence", 0) or 0
    llm_domain = parsed.get("domain")
    laya_domain = (laya_attrs or {}).get("domain")
    if llm_domain in COVERED_DOMAINS:
        chosen = llm_domain
    elif laya_domain in COVERED_DOMAINS:
        chosen = laya_domain
        parsed["domain_arbitration"] = "laya (LLM domain not covered by the corpus)"
    else:
        chosen = llm_domain or laya_domain or "operations"
        parsed["domain_arbitration"] = "neither model named a covered area"
    if chosen != llm_domain:
        parsed["domain_arbitration"] = parsed.get("domain_arbitration") or "laya"
    parsed["domain"] = chosen
    if laya_attrs:
        parsed.setdefault("laya", {})
        if isinstance(parsed.get("laya"), dict):
            parsed["laya"]["laya_domain_label"] = laya_domain
            parsed["laya"]["laya_domain_confidence"] = laya_dom_conf
    if laya_attrs:
        parsed["laya"] = laya_attrs.get("laya")
    return parsed, {"llm_calls": calls, "laya": laya_meta}


async def redflag(text: str, *, memory: bool = True, promoted: set[str] | None = None,
                  seed: str | None = None) -> dict[str, Any]:
    """Assess a free-text business decision. `seed` is an optional known domain/type for tests."""
    s = settings()
    now = datetime.now(timezone.utc)
    out: dict[str, Any] = {
        "mode": None,
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
    out["mode"] = attrs.get("mode", "decision")
    domain, dtype = attrs.get("domain"), attrs.get("decision_type")

    # Ordinary conversation: a plain reply, with no recall and no verdict, exactly as the streaming path
    # does. Both endpoints must agree, or the same message gets reviewed on one and answered on the other.
    if out["mode"] == "chat":
        reply, cmeta2 = await chat_text(CHAT_SYSTEM, text, max_tokens=800)
        out["engine"]["llm_calls"] += cmeta2.get("llm_calls", 0)
        out["reply"] = reply
        out["precedents"] = []
        out["declined"] = []
        return out

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
        # The refusal is the answer; the guess is opt-in extra, and is labelled so it cannot be confused
        # with a memory-grounded verdict.
        guessed, gmeta = await chat_json(
            NO_PRECEDENT_GUESS_SYSTEM,
            f"DECISION THE USER IS CONSIDERING\n{text}\n\n"
            f"CLASSIFIED AS: domain={domain}, type={dtype}\n"
            "There is no company precedent. Give the refusal-consistent verdict plus a labelled guess.",
            max_tokens=1500,
        )
        out["engine"]["llm_calls"] += gmeta.get("llm_calls", 0)
        out["guess"] = _guess_block(guessed, domain, dtype)
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

async def redflag_stream(text: str, *, promoted: set[str] | None = None,
                         history: list[dict[str, str]] | None = None):
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

    `history` carries the prior turns of the conversation. Its presence changes the routing: a follow-up is
    conversation about the earlier review, not a fresh decision to review, so it is always answered as chat
    with the prior turns in context.
    """
    s = settings()
    now = datetime.now(timezone.utc)

    def ev(kind: str, **data) -> str:
        return "data: " + json.dumps({"type": kind, **data}, default=str) + "\n\n"

    try:
        # A follow-up is conversation about the review already given, regardless of how decidable it reads in
        # isolation. Without this, "what if we cap it at 15 percent?" gets reviewed from scratch and loses the
        # thread it belongs to.
        #
        # This is settled BEFORE the classify event is emitted: doing it afterwards left the event reporting
        # the raw classification, so the UI kept rendering a follow-up as a full dossier even though the
        # answer itself was conversational.
        is_followup = bool(history)

        yield ev("status", message="classifying the decision", step="classify")
        attrs, cmeta = await classify(text)
        if is_followup:
            attrs["mode"] = "chat"
            attrs["follow_up"] = True
        domain, dtype = attrs.get("domain"), attrs.get("decision_type")
        yield ev("classify", domain=domain, decision_type=dtype, mode=attrs.get("mode"),
                 follow_up=attrs.get("follow_up", False),
                 intent=attrs.get("intent"), rationale=attrs.get("rationale"),
                 laya=attrs.get("laya"), llm_calls=cmeta.get("llm_calls", 0))

        # Ordinary conversation: answer it and stop. No recall, no verdict, no citations, and the frontend
        # renders it as a plain chat bubble rather than a reviewed decision.
        if attrs.get("mode") == "chat":
            yield ev("status", message="replying", step="chat")
            async for kind, piece in chat_stream(
                FOLLOWUP_SYSTEM if is_followup else CHAT_SYSTEM, text,
                reasoning=True, history=history,
            ):
                if kind == "reasoning":
                    yield ev("reasoning", text=piece)
                else:
                    yield ev("delta", text=piece)
            yield ev("done", engine={"ranker": "skipped (not a decision)", "llm_calls": cmeta.get("llm_calls", 0),
                                     "mode": "chat", "model": s.llm_model},
                     facts_used=[], citations_in_prose=[], attribution_unverified=[])
            return

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
            # The refusal above is the answer. The guess below is a separate, labelled block so it can
            # never be mistaken for company memory: it is forbidden from citing an id and is scanned for
            # one before it reaches the client.
            yield ev("status", message="no precedent, thinking it through", step="guess")
            # Streamed, not a blocking call: on a no-precedent prompt the guess IS the main content, so it
            # should type itself out with a reasoning trace like every other answer rather than appearing
            # all at once after a pause.
            guessed_buf: list[str] = []
            async for kind, piece in chat_stream(
                NO_PRECEDENT_GUESS_STREAM_SYSTEM,
                f"DECISION THE USER IS CONSIDERING\n{text}\n\n"
                f"CLASSIFIED AS: domain={domain}, type={dtype}\n"
                "There is no company precedent. Give the refusal-consistent verdict plus a labelled guess.",
                max_tokens=1800,
                reasoning=True,
            ):
                if kind == "reasoning":
                    yield ev("reasoning", text=piece)
                else:
                    guessed_buf.append(piece)
            parsed_guess = _parse_guess_block("".join(guessed_buf))
            yield ev("guess", **(_guess_block(parsed_guess, domain, dtype)))
            yield ev("done", engine={"ranker": "deterministic",
                                     "llm_calls": cmeta.get("llm_calls", 0) + 1,
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
        async for kind, piece in chat_stream(STREAM_OPINION_SYSTEM, user, max_tokens=3000, reasoning=True):
            if kind == "reasoning":
                yield ev("reasoning", text=piece)
                continue
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
