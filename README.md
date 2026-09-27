# pre-mortem

> A chatbot that turns into a reviewer the moment you put a decision to it.

Describe a decision you are considering, in plain English. The agent searches what your organisation has
actually done before, flags what went wrong, and cites each past decision by id. When there is no
precedent it says so instead of inventing one.

Built for the *AI Agents That Learn Using Hindsight* hackathon. Memory layer: [Hindsight](https://hindsight.vectorize.io/).
Local classification: [Laya](https://huggingface.co/convaiinnovations/laya).

---

## The idea, explained like you're 5

Imagine your company is a person who has made a lot of decisions. Some worked. Some went badly.

Right now that person has no memory. So every time you ask "should we give this customer a big discount?",
nobody remembers that you did that twice before and it hurt both times.

This is a notebook for the company. Before you decide something, you ask it. It looks up every time you
did something similar and tells you:

> "You did this twice. Both times the customer asked for a discount and you said yes without asking for
> anything back. Both times your money went down. One time you asked for a longer contract in return, and
> that one was fine. So ask for the longer contract."

And if it has never seen your decision before, it says:

> "I don't know this one. I have nothing to compare it to."

Saying "I don't know" is the important part. That is what makes it not a liar.

*(This section is the script seed for the demo video. Keep it.)*

---

## Three modes

It is a conversation, not a form. Every message is routed by Laya into one of three modes before anything
else happens, so you can say hello, ask about your own history, or put a real decision on the table, in any
order, in the same thread.

| Mode | Trigger | What comes back |
|---|---|---|
| `decision` | the message proposes an action to judge ("should we...", "I want to...") | the full review: verdict, precedents, difference, guardrail, open questions |
| `query` | a question about the company's own history ("what cost the most?", "what did we decide about X?") | the records themselves, unfiltered, with cited ids. No verdict |
| `chat` | greetings, thanks, questions about the tool, follow-ups | a plain conversational reply. No recall, no verdict, no citations |

The routing is measured, not asserted. Laya's `domain_probability` separates the classes and costs nothing
extra:

| Message | Mode | p |
|---|---|---|
| "hey, how are you doing today?" | `chat` | 0.29 |
| "thanks, that helps" | `chat` | 0.21 |
| "what did we decide about the Acme renewal?" | `query` | 0.27 |
| "Should I give Acme a 30 percent discount to close the renewal this quarter?" | `decision` | 0.99 |
| "We are considering opening an office in Lisbon." | `decision` | 0.94 |

Gates live in `api/app/bizlookalike.py`: at or above `LAYA_MODE_DECISION = 0.60` it is a decision, at or
below `LAYA_MODE_CHAT = 0.15` it is chat or query, and in between the LLM arbitrates. The band Laya decides
alone is deliberately tiny, because the two errors are not symmetric: a decision answered conversationally
silently withholds the entire product, while a greeting that gets reviewed is merely noisy.

One tie-break rule, learned the hard way: a message that both proposes an action and asks about the past is
a `decision`, never a `query`. A review cites the records anyway and adds the judgement on top; a `query`
would withhold it.

## The grown-up version

Put a decision to it and the review comes back with:

- a **verdict** derived from what actually happened to your past decisions, not from an opinion,
- the **precedents**, each cited by id with how much evidence stands behind it,
- the **difference**: the one detail that separated a past decision that went badly from a
  near-identical one that went fine,
- the **guardrail**: the specific condition, taken from your own recorded lessons, that would make it safe,
- **open questions** to answer before deciding,
- and a refusal (`no precedent`) when your history does not cover it.

## Follow-ups

Every message sent with prior conversation is a follow-up, and every follow-up is `chat`, whatever it reads
like on its own. The prior turns go to the model, so "what if we cap it at 15 percent?" stays a conversation
instead of being reclassified as a fresh decision and reviewed from scratch.

- Transport: `POST /api/biz/redflag/stream` with `{"prompt": str, "history": [{"role", "content"}]}`. POST
  because a conversation history does not fit in a query string. The GET variant still works for a first
  message, taking `?prompt=` or `?preset=`.
- History is capped at 12 turns client-side.
- Follow-ups are answered with a different system prompt: they may only cite ids that already appeared in
  the earlier answer, and they may not issue a new risk rating.
- The frontend carries precedents forward from the most recent turn that had them, so ids in follow-up
  prose still render as pills.

## Reasoning trace

Our prose model emits `reasoning_content` before its answer. We keep it and stream it as a `reasoning` SSE
event, rendered collapsed behind a disclosure in the UI so it is available on camera without ever competing
with the answer. Measured: 2126 to 7027 characters on a full discount review, 58 to 200 on a greeting.

## Why this shape

| | A generic AI opinion | pre-mortem |
|---|---|---|
| Source | the model's training data | your organisation's own recorded decisions |
| Citations | none | every claim carries a decision id, verified against the corpus |
| Failure mode | confident invention | says `no precedent` and stops |
| Learns from | nothing | its own ignored warnings, which it then leads with |

## How Hindsight is used

Memory is the entire artifact. Remove Hindsight and there is no corpus, no evidence counts, no trend, and
no way to prove the reasoning.

| Piece of the product | Hindsight surface |
|---|---|
| One document per past decision (what was decided, the rationale, the result, the lesson) | `retain` with `metadata` = decision id / domain / decision type / outcome |
| Consolidated knowledge: *"Acme discounts without a term commitment damaged margin (evidence 2, strengthening)"* | `observation` with proof count + freshness trend |
| The evidence number shown on every card | observation proof count, no hand-tuning |
| "This pattern is getting worse" | freshness trend `strengthening` / `weakening` / `stale` |
| Exact source text behind a claim | `recall(include_chunks=True)` |
| Refusing to assert an uncited cause | `directives` |
| Refusing instead of guessing | `disposition` skepticism 4 / literalism 5 / empathy 2 |
| The agent answering from its own reasoning, on camera | `reflect` with `response_schema` |
| Showing the literal assembled prompt | `banks.preview_prompt()` |
| Forcing consolidation before a demo | `banks.recover_consolidation()` |

**Lookahead is controlled honestly.** `query_timestamp` is a ranking hint on API 0.10.1, it does **not**
filter results (measured: identical result sets for any timestamp). So the replay filters by
`occurred_start` in code, and the live demo seeds only up to the day being evaluated. The README says this
is our evaluation logic rather than a server guarantee, because that is what is true.

The corpus is 72 decisions across 10 domains, with outcomes of 47 good / 22 bad / 3 mixed. The live bank
holds 77 documents and 68 observations. Nothing here is real company data: the corpus is synthetic, and the
mechanism is the contribution, not the data.

## Where Laya fits (and where it does not)

Laya is a **System One model**: it does not write text, it evaluates a state and returns typed answers with
calibrated probabilities. It runs locally, offline, Apache-2.0.

It replaces the classification call that used to cost an LLM request, adds two signals an LLM never gave us,
and now routes every message into a mode:

```
choice -> domain (pricing / hiring / vendor / …)   measured 0.9487 / 0.9981 / 0.9423, all correct
score  -> reversibility (Easy / Moderate / Hard)
noul   -> whether value is being given away for nothing, and blast radius
p      -> which of the three modes this message belongs to
```

Laya's own authors report **67.3% vs 59.6%** on 108 hand-labelled cases. That is a real but modest edge on
a small sample, so Laya is used where a calibrated probability is genuinely useful and a mistake is cheap:
classification, mode routing, and gating. **The verdict is never produced by a model.** Four separate jobs,
no overlap:

```
Laya classifies  ->  Hindsight remembers  ->  the ranker decides  ->  the LLM writes prose
```

## Endpoints

The business path, which is the product:

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/biz/prompts` | the preset prompts (A through E) |
| `POST` | `/api/biz/redflag` | non-streaming review |
| `GET` | `/api/biz/redflag/stream` | SSE review, `?prompt=` or `?preset=` |
| `POST` | `/api/biz/redflag/stream` | SSE review with a `history` array (follow-ups) |
| `GET` | `/api/biz/ledger` | calibration: flags raised / ignored / costed, promoted classes |
| `GET` | `/api/biz/bank` | bank stats and directives |
| `POST` | `/api/biz/seed` | seed the corpus |
| `POST` | `/api/biz/consolidate` | force consolidation, for a demo |
| `GET` | `/api/biz/ground-truth` | the corpus, for scoring |

The legacy deploy path from the earlier pivot is still served alongside it:
`POST /api/assess`, `GET /api/presets`, `GET /api/metrics`, `POST /api/replay`, `POST /api/seed`,
`GET /api/bank`, `GET /api/ledger`, `GET /api/ground-truth`, `POST /api/consolidate`.

### Health

Two endpoints, and the difference is the point.

- `GET /health` is **liveness**. It is answered entirely from local state: config problems, bank id, model
  names, Laya status. No network call. This is what the container healthcheck hits.
- `GET /health/deep` is **readiness**. It adds Hindsight reachability, bank config, directives and the
  document list. Slow, and therefore never used by the healthcheck.
- `POST /api/health/llm` is a live call to the prose model.

The split exists because `/health` used to fan out to Hindsight Cloud with no timeout against a 5 second
healthcheck. Under latency the container was marked unhealthy, Traefik withdrew its route, and every URL on
the API host returned Traefik's plain-text `404 page not found` while the app was running fine. A
third-party API must not be able to unroute the deployment.

`/health` reports `bank_id: bizdecisions` and a `banks` object of `{business: bizdecisions, legacy_deploy: premortem}`.

## Setup

```bash
cp .env.example .env      # HINDSIGHT_API_KEY, OPENCODE_GO_API_KEY, NEXT_PUBLIC_API_BASE_URL
docker compose up --build # api :8000, web :3000

# first run only: build the corpus, then WAIT for observations (they are a background job)
curl -X POST localhost:8000/api/biz/seed
python api/scripts/smoke.py --url http://localhost:8000
```

Local dev without containers: `uvicorn app.main:app --reload` in `api/`, `npm run dev` in `web/`.

No Groq key, no OpenAI key. Hindsight runs on Vectorize Cloud; our own LLM calls go to **OpenCode Go**
(`deepseek-v4.1-flash`); classification and mode routing are local via **Laya** (ONNX int4, 275MB,
Apache-2.0, baked into the api image). `recall` costs no LLM at all, which is why the replay and the metrics
are free and reproducible.

Two checks worth running against any base URL:

```bash
python3 api/scripts/mode_check.py https://premortem-api.lexcontra.com          # mode contract, 9 messages
python3 api/scripts/conversation_check.py https://premortem-api.lexcontra.com  # follow-ups stay chat
```

## Layout

```
pre-mortem/
  README.md              <- this file (the 5-year-old explainer is the video cold open)
  PLAN.md                <- master plan: criteria mapping, SWOT, metrics, risks
  docs/
    ARCHITECTURE.md      <- topology, API contracts, ranking, failure handling
    MODELS.md            <- OpenCode Go + Hindsight, verified behaviour, corrections, fallbacks
    LAYA.md              <- the local classifier: measured behaviour and the traps
    DATA.md              <- the deploy corpus, patterns, ground truth
    DEMO.md              <- video script, shot list, article + social outline
    CHECKLIST.md         <- build, pre-record, submission gates
  api/                   <- FastAPI: owns Hindsight, ranking, replay, streaming
  web/                   <- Next.js: the chat window
  docker-compose.yml     <- api + web (Hindsight and Laya are external/baked)
```

## Scope, stated plainly

Decision support only. It reports what happened in your own history, with citations. It does not make the
decision, does not file anything, and does not give legal, tax, or financial advice. Synthetic data only.
