# Architecture

Technical spec for `pre-mortem`. Two deployables (FastAPI backend, Next.js frontend), one Hindsight
instance, one LLM provider (9Router). Model and deployment choices live in `MODELS.md`.

Three things to know before reading further:

- The product is the **business path** (`/api/biz/*`). The older deploy-oriented paths (`/api/*`) are a
  pivot leftover. They are still served and still work, but nothing in the product calls them.
- Every message is routed by Laya into one of three modes before anything else happens (section 3).
- `/health` never touches the network. That is not a style choice, it was an outage (section 3.1).

## 1. Why the UI is separate

The UI carries 15% of the score and the demo *is* the UI. Splitting it means:

- The frontend is pure presentation, so it can be made genuinely good (design tokens, typography, an
  editorial reading column) instead of fighting a Python layout engine.
- The API owns memory and can be tested without a browser (fast, headless, assert-based).
- Judges can be given the Hindsight Control Plane for a memory-side view and the product UI on `:3000`, and
  they are clearly different things.
- The replay and metrics are precomputed server-side, so the UI stays instant during recording.

## 2. Topology

```
browser ──▶ Next.js :3000 ──/api/biz/*──▶ FastAPI :8000 ──▶ Hindsight ──▶ LLM provider
                  │                            │
                  │                            ├── Laya (local ONNX int4, no network)
                  │                            └── owns seeding, replay, metrics, ledger
                  └── Hindsight Control Plane (judges only, not the product)
```

Hard rules:
- The browser **never** talks to Hindsight. All memory access is behind FastAPI, so there is one contract
  and one place to cache.
- FastAPI is the only writer to Hindsight.
- `NEXT_PUBLIC_API_BASE_URL` is the single coupling between the two.
- The API host owns every Hindsight call, including the ledger reads.

## 3. The three-mode router

Laya classifies every message locally and returns, among other signals, a `domain_probability`. That one
number decides which of three modes the message is in. Routing on the classification we were already paying
for is why the router costs nothing extra.

| Mode | Trigger | Behaviour |
|---|---|---|
| `decision` | the message proposes an action to judge ("should we...", "I want to...") | full review: verdict, precedents, difference, guardrail, open questions |
| `query` | a question about the company's own history ("what cost the most?", "what did we decide about X?") | recalls the records unfiltered, answers from them with cited ids, no verdict |
| `chat` | greetings, thanks, questions about the tool, follow-ups | plain conversational reply, no recall, no verdict, no citations |

Measured values (production, live):

| Message | Mode | `domain_probability` |
|---|---|---|
| "hey, how are you doing today?" | `chat` | 0.2923 |
| "thanks, that helps" | `chat` | 0.214 |
| "what did we decide about the Acme renewal?" | `query` | 0.265 |
| "what caused the most loss in the year?" | `query` | not recorded |
| "Should I give Acme a 30 percent discount to close the renewal this quarter?" | `decision` | 0.9883 |
| "We are considering opening an office in Lisbon." | `decision` | 0.9422 |

### 3.1 Gate thresholds

Constants in `api/app/bizlookalike.py`:

| Constant | Value | Meaning |
|---|---|---|
| `LAYA_MODE_DECISION` | `0.60` | at or above, the mode is `decision`, whatever the LLM said |
| `LAYA_MODE_CHAT` | `0.15` | at or below, the mode is `chat` or `query` |

Between the two thresholds the band is deliberately wide and the **LLM arbitrates**: it picks `chat` or
`query`, and defaults to `decision` when it picks neither. The arbitration is recorded on the classify
result as `mode_arbitration` (e.g. `laya ambiguous (0.42), model decided`), so a surprising route is
inspectable rather than mysterious.

Why the band is wide: the measurement that justifies it. On this corpus greetings and thanks score 0.21 to
0.45, context-only statements about a decision score 0.18 to 0.23, and real decisions score 0.93 to 0.99. A
high score is reliably a decision and a low score is reliably not one, but the two low cases overlap. A
statement of context with no proposed action ("Acme's renewal is at risk and their champion wants a
gesture") scores 0.18, while "thanks, that helps" scores 0.21. The signal cannot separate those two, so only
messages Laya scores as emphatically empty skip the model entirely.

The asymmetry drives everything else: a decision answered conversationally silently withholds the entire
product, whereas a greeting that gets reviewed is merely noisy. So the band where Laya decides alone is kept
tiny.

### 3.2 Tie-break: action plus history question

A message that BOTH proposes an action and asks about the past is a `decision`, never a `query`. A review
cites the records anyway and adds the judgement on top; a `query` would withhold it. This was a real
regression, not a hypothetical. The worked example is preset E ("a partner is asking for exclusivity... I
want to sign it quickly... What has burned us on deals like this before?"), which must be a `decision`.

The rule is written into `CLASSIFY_SYSTEM` so the model applies it during arbitration.

## 3.3 Health endpoints and why they are split

| Endpoint | Role | Network |
|---|---|---|
| `GET /health` | LIVENESS. Answered entirely from local state: config problems, bank id, models, Laya status. This is what the container healthcheck hits. | none |
| `GET /health/deep` | READINESS. Adds Hindsight reachability, bank config, directives, document list. Slow, so not the healthcheck. | yes |
| `POST /api/health/llm` | Explicit LLM reachability check. Costs a tiny LLM call, so it is a POST you choose to send. | yes |

The outage this split exists for: `/health` previously fanned out to Hindsight Cloud with no timeout,
against a 5s container healthcheck. Under latency the container was marked unhealthy, Traefik withdrew its
route, and **every URL on the API host returned Traefik's plain-text `404 page not found` while the app was
running fine**. A third-party API must never be able to unroute the deployment.

`/health` reports `bank_id: bizdecisions` and a `banks` object `{business: bizdecisions, legacy_deploy:
premortem}`. The business bank is named first because it is the one the product reads; `bank_id` keeps the
older deploy bank's value so an existing reader does not silently get a different answer. `/health/deep`
reports the business bank's document count for the same reason: reporting the legacy count made it disagree
with `/api/biz/bank` (42 vs 77) and read as a broken memory store.

Laya is lazy-loaded on first use, so `/health` reports `loaded: false` until the first classify. `enabled:
true` is the honest idle answer. The compose `start_period` is generous because the first Laya load builds
the ONNX session (9.1s measured, more on a cold host) and the healthcheck must not fail the container
during that window.

## 4. Endpoints

### Business path (the product)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/biz/prompts` | the preset prompts, with expected domain/type and what a good answer looks like |
| `POST` | `/api/biz/redflag` | non-streaming review. Body `{prompt, preset, memory, engine, use_ledger}` |
| `GET` | `/api/biz/redflag/stream` | SSE review, `?prompt=` or `?preset=` |
| `POST` | `/api/biz/redflag/stream` | SSE review with `{"prompt", "history": [{"role","content"}]}`, the follow-up path |
| `GET` | `/api/biz/ledger` | calibration: flags raised / ignored anyway / costed, promoted classes |
| `GET` | `/api/biz/bank` | bank config, directives, agent stats, document list |
| `POST` | `/api/biz/seed` | seed the business corpus (72 retains, each costing extraction tokens), seed the ledger, consolidate, write ground truth |
| `POST` | `/api/biz/consolidate` | trigger consolidation, optionally wait for observations |
| `GET` | `/api/biz/ground-truth` | the corpus as written by seed, for scoring |

SSE event sequence from `bizlookalike.redflag_stream`: `status` -> `classify` -> (`status` -> `precedents`
-> prose, in one of three shapes below) -> `done`, with `error` on failure carrying the partial answer. The
three prose shapes are `query` (records then answer), `chat` (`delta` only), and `decision` (`verdict` and
`precedents` before the prose, so the risk banner renders while the text is still being written). The
no-precedent decision path emits `guess` before `done`.

### Legacy deploy path (pivot leftover, still served)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/assess` | preset-driven assessment of a deploy change, `memory` and `engine` flags |
| `GET` | `/api/presets` | the 3 pending deploy changes |
| `GET` | `/api/metrics` | cached precision/coverage by epoch, derivable-vs-found coverage |
| `POST` | `/api/replay` | run the epoch replay, cache to `data/replay.json` |
| `POST` | `/api/seed` | seed the 40-launch deploy corpus |
| `GET` | `/api/bank` | legacy bank stats and config |
| `GET` | `/api/ledger` | legacy flags, ignored counts, promoted classes |
| `GET` | `/api/ground-truth` | legacy ground truth |
| `POST` | `/api/consolidate` | consolidation for the legacy bank |
| `GET` | `/api/prompt-preview` | the literal assembled Hindsight prompt |

Nothing in the product UI calls these. They are kept because they are correct and cost nothing to serve,
and because the replay numbers in `data/replay.json` come from them.

## 5. Follow-ups and the POST transport

A message sent with prior conversation is ALWAYS `chat`, whatever it reads like in isolation, and the prior
turns are passed to the model. Rationale: "what if we cap it at 15 percent?" would otherwise be classified as
a fresh decision and reviewed from scratch, losing the thread.

| Piece | Behaviour |
|---|---|
| Transport | `POST /api/biz/redflag/stream` with `{"prompt": str, "history": [{"role","content"}]}`. POST because history does not fit in a query string. The GET variant still works and takes `?prompt=` / `?preset=`. |
| Client cap | history is capped at 12 turns client-side (`HISTORY_LIMIT`), and the server takes the last 12 as well |
| Prompt | a follow-up is answered with `FOLLOWUP_SYSTEM`, which permits citing only ids already present in the earlier answer and forbids a fresh risk rating |
| Events | the follow-up flag is settled BEFORE the `classify` event is emitted, so the UI does not render a conversational reply as a full dossier |
| Frontend | precedents are carried forward from the most recent turn that had them, so ids in follow-up prose still render as pills |

The ordering point is a fixed bug, not a nicety: setting the flag after emitting `classify` left the event
reporting the raw classification, and the UI kept drawing a dossier over a chat answer.

## 6. Reasoning lane in `llm.chat_stream`

`OpenCode Go` emits `reasoning_content` deltas before `content`. Those used to be discarded.

- `llm.chat_stream(..., reasoning=True)` yields `("reasoning", text)` and `("content", text)` pairs. Callers
  must unpack: `async for kind, piece in chat_stream(...)`.
- Tuple-shaped rather than two generators so a single upstream stream feeds both lanes in order.
- Surfaces as a `reasoning` SSE event, rendered collapsed behind a disclosure
  (`web/components/reasoning.tsx`), never competing with the answer.
- Measured: 2126 to 7027 characters on a full discount review, 58 to 200 on a greeting.

Because both lanes are `continue`-separated in the stream loop, reasoning never enters the answer buffer,
so it cannot leak into the parsed review or into citation counting.

## 7. Backend layout

```
api/
  app/
    main.py            FastAPI app, CORS, every route
    config.py          env loading, bank ids, llm model + fallback, MIN_PROOF
    bizlookalike.py    classify, mode gate, recall + rank + verdict, SSE generator, prompts
    bizcorpus.py       the 72 business decisions, 10 domains, prompts A-E
    bizcorpus_extra.py the richer half: owners, amounts at stake, context, patterns B7-B10, prompts D-E
    bizledger.py       the ignored-warning ledger for business decisions
    corpus.py          the legacy 40-launch deploy corpus + 3 deploy presets
    lookalike.py       the legacy recall/rank/assess path
    ledger.py          legacy flags, ignored outcomes, promoted classes
    rank.py            deterministic ranker, verdict vocabulary, attribution cross-check
    laya_client.py     local ONNX classifier wrapper, lazy load, status
    hindsight.py       client factory, bank bootstrap, seed, recall, reflect, consolidation, stats
    llm.py             chat_json / chat_text / chat_stream, retry ladder, reasoning lane
    replay.py          legacy epoch replay -> replay.json
  scripts/
    smoke.py           39 checks against a live URL, business path, `--deep` adds more
    mode_check.py      routes 9 messages and asserts the mode contract for each
    conversation_check.py opening question reviewed, three follow-ups all chat
  tests/test_e2e.py    assert-based end-to-end against real Hindsight
```

## 8. Ranking, deterministic and shown

```python
def score(mem, now, promoted):
    # total = proof*2 + recency_weight + trend_penalty + ledger_boost
    # proof*2        : evidence beats everything
    # recency_weight : newer precedents first, 1.0 -> 0.2 across the window
    # trend_penalty  : negative for trend in ("weakening", "stale")
    # ledger_boost   : positive when "domain@decision_type" is ledger-promoted
    # No LLM. Deterministic. Ties break on decision id so the order is stable across runs.
```

`verdict()` in `api/app/rank.py` spans both vocabularies (`incident`/`degraded` AND `bad`/`mixed`/`good`).
"Precedents exist but none records a failure" is `medium`, not `low`. `outcome: None` renders `OUTCOME NOT
RECORDED`, never "clean". Every cited id is cross-checked against the corpus ground truth (76 of 77 ids),
because Hindsight consolidated observations carry empty metadata.

Gating: nothing below `MIN_PROOF` (default 1) may be shown as a precedent. When nothing clears the bar in
the relevant `domain + decision_type`, the answer is the refusal, with coverage and up to 3 declined entries
carrying a reason.

The no-precedent guess is fenced off hard: the guess prompt forbids citing an id, and `_guess_block()`
strips any id it finds and caps a HIGH confidence at MEDIUM, so a guess can never launder itself into a
citation.

## 9. Laya

ONNX int4 `techtheist/laya-onnx`, 275MB, Apache-2.0. `LOAD 9.1s`, `PREDICT 1.4-3.0s`, peak RSS 996MB.
`torch 2.14.0+cpu` is a hard dependency via `laya/common.py`; `libgomp1` is required. It contributes
`domain_probability`, `reversibility_label`, `gives_value_without_commitment`, `is_high_blast_radius`.

Laya's taxonomy has no bucket for compliance, security or partnership. Its domain label must NOT override the
LLM when the LLM names a domain the corpus actually covers, and `COVERED_DOMAINS` is derived from the corpus
so the two can never drift. Getting this wrong made an audit question classify as `launch` at 0.825
confidence and cite launch decisions.

Laya is the router and the signal provider, NOT the decision-maker. The verdict comes from the recorded
outcomes of past decisions, computed by the deterministic ranker. The model only writes the sentences.

## 10. LLM usage

Every chat call sends `x-opencode-session: $OPENCODE_SESSION`. OpenCode Go rejects chat without it
(`MissingSessionID`), so this is a hard requirement.

| Call | Shape | Why |
|---|---|---|
| Classify | `chat_json`, `response_format: json_object`, schema described in the prompt | the gateway only supports JSON mode, not full JSON schema, so the fields are described in `CLASSIFY_SYSTEM` |
| Review prose | `chat_stream(..., reasoning=True)` | streams `reasoning` and `delta` events; `parse_review` reads HEADLINE/WHY/DIFFERENCE/GUARDRAIL/QUESTIONS out of the buffer |
| Follow-up / chat / query | `chat_text` with `FOLLOWUP_SYSTEM`, `CHAT_SYSTEM` or `QUERY_SYSTEM` | `history` is passed through on every lane |
| No-precedent guess | `chat_json` | must return an id-free guess, checked again in Python |
| Provider fallback | fallback model with the retry ladder | primary -> one repair attempt -> fallback, and a fallback that has failed once in this process is not tried again |

## 11. Frontend

```
web/
  app/layout.tsx        fonts (self-hosted), tokens, flash-prevention theme script
  app/page.tsx          the one screen: conversation, review, sources, sidebar
  app/globals.css       design tokens
  components/
    editorial.tsx       serif hedging, DecisionId, Label
    sources.tsx         hidden-by-default citation pills, preview popover, AnnotatedProse
    reasoning.tsx       the collapsed thinking trace
    guess.tsx           the labelled no-precedent guess panel
    sidebar.tsx         theme, evidence default, engine detail, calibration block, status line
    theme-toggle.tsx    ThemeChoice (the one the sidebar uses)
  lib/api.ts            typed client, fetch + ReadableStream (EventSource cannot POST)
  lib/settings.ts       UI preferences, persisted
```

Design intent, in priority order:
1. **The answer is the hero.** One reading column, evidence as a footnote apparatus rather than competing
   panels.
2. **Every number is attributable.** Decision ids render as pills next to the claim; an id that is not in the
   precedent set stays plain mono text rather than dressing up as evidence.
3. **The refusal state must look confident, not broken.** `no_precedent` gets the same visual weight as a risk
   card, with coverage and the declined list; the guess follows in a labelled panel at full width.
4. **Risk colour is the only saturated colour in the product.** When something is red it always means the
   same thing.
5. **Theme follows the OS live** (system -> light -> dark), key `pm-theme`, default system.

Fonts are self-hosted from `web/public/fonts/` because `next/font/google` fetches at build time and the
Docker builder has no network.

No automated browser test exists: Playwright was never installed and there is no Chrome binary on the build
host, so the UI is verified from built CSS, served HTML and the deployed bundle, not from rendered pixels.

## 12. Testing

| Layer | Tool | What is actually asserted |
|---|---|---|
| Mode contract | `api/scripts/mode_check.py` | 9 messages, each asserted against its mode contract: `chat` has no verdict and no cites, `query` retrieves records and gives no verdict, `decision` has a verdict. Includes the action+history regression case. |
| Follow-ups | `api/scripts/conversation_check.py` | the opening question is reviewed; three follow-ups are all `chat` with `follow_up=true` and no verdict re-issued |
| Live smoke | `api/scripts/smoke.py` | 39 checks against any base URL, business path, including the SSE event sequence. `--deep` adds bank and ledger checks. |
| API e2e | `api/tests/test_e2e.py` | assert-based, real Hindsight; default run makes no LLM calls |

Run against any base URL: `python3 api/scripts/mode_check.py https://premortem-api.lexcontra.com`

## 13. Failure handling

| Failure | Handling |
|---|---|
| Hindsight slow or down | `/health` still answers (it never calls out); `/health/deep` reports the error without taking the deployment down |
| Hindsight unreachable at request time | the route fails with a typed error and the UI shows a connection error, not a spinner forever |
| Laya unavailable | `classify` falls back to the LLM alone and marks the result degraded; the product still works |
| Classify returns unusable JSON | falls back to Laya's own attributes, which still carry a real domain |
| Our JSON-mode call returns prose | detect the unparsable body, retry once, then the fallback model, then render the missing piece rather than a broken card |
| Observations not consolidated | `POST /api/biz/consolidate`, and it runs at seed time |
| Contradictory precedents | both rendered, the card states why, the agent never averages them into a comforting middle |
| Bad/missing env | `settings().problems()` is reported by `/health`; `next build` must not require runtime secrets |

## 14. Non-goals, permanent

No live deploys from the product. No auth. No database of our own (Hindsight owns the memory). No second use
case. No real customer data. Nothing in the product ships, approves, or advises.
