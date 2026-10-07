# pre-mortem

**[Live demo: premortem.lexcontra.com](https://premortem.lexcontra.com/)** — open it and try one of the
preset decisions, or type your own.

> A chatbot that turns into a reviewer the moment you put a decision to it.

Describe a decision you are considering, in plain English. The agent searches what your organisation has
actually done before, flags what went wrong, and cites each past decision by id. When there is no
precedent it says so instead of inventing one.

It also lets you **add decisions the company has made**, so the history grows from use rather than staying a
fixed corpus. Added decisions start with no outcome recorded, and are asked about later; once you say how one
turned out, it can count as evidence rather than merely as context.

Built for the *AI Agents That Learn Using Hindsight* hackathon. Memory layer: [Hindsight](https://hindsight.vectorize.io/).
Local classification: [Laya](https://huggingface.co/convaiinnovations/laya). Prompt store: Postgres + pgvector.

| | |
|---|---|
| Live demo | https://premortem.lexcontra.com/ |
| API | https://premortem-api.lexcontra.com/ (`GET /health`) |

> **Read the write-up:** the four places making the system refuse to answer
> fought the model's instinct to be helpful, plus the bugs that only appeared
> once it was running, is at
> [adityavikram.dev/blog/pre-mortem-refuses-to-answer](https://adityavikram.dev/blog/pre-mortem-refuses-to-answer).

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
| A decision the user added during the session, citable by id later | `retain` from `POST /api/biz/history/commit`, on a human yes |
| Recording what actually happened to an added decision | re-`retain` under the same `document_id` from `/api/biz/history/resolve`, which supersedes rather than duplicates |
| **Not** asking people's typed prompts | deliberately absent: prompts are recorded and vectorised in the prompt store (Postgres + pgvector), never retained. See *Prompt history* under Endpoints |
| Forcing consolidation before a demo | `banks.recover_consolidation()` |

**Lookahead is controlled honestly.** `query_timestamp` is a ranking hint on API 0.10.1, it does **not**
filter results (measured: identical result sets for any timestamp). So the replay filters by
`occurred_start` in code, and the live demo seeds only up to the day being evaluated. The README says this
is our evaluation logic rather than a server guarantee, because that is what is true.

**What explicitly does not go into Hindsight.** Every prompt run is recorded and vectorised for
cross-referencing, but prompts are **not** retained. Hindsight holds the curated decision record; the prompt
store (Postgres + pgvector) holds what people asked. The only bridge is the commit endpoint, on a human yes,
so unreviewed text can never become evidence the ranker cites. See *Prompt history* above.

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

### Prompt history (the store, and the commit gate)

Every prompt run is recorded to Postgres and vectorised, so a new prompt can be cross-referenced against
the ones before it. Recording is automatic; **adding a decision to the company's knowledge base is not**.
That is the whole point of the split: a prompt a user typed is not company knowledge until someone decides
it is, and the store is deliberately separate from Hindsight so unreviewed text can never enter the
evidence the ranker cites.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/biz/history` | recent prompts, newest first, with which are committed |
| `GET` | `/api/biz/history/stats` | store counts and embedder status |
| `GET` | `/api/biz/history/unresolved` | committed decisions with no recorded outcome yet |
| `POST` | `/api/biz/history/recall` | cross-reference arbitrary text without recording it |
| `POST` | `/api/biz/history/draft` | draft a decision record from a review, for the user to edit |
| `POST` | `/api/biz/history/commit` | writes a reviewed decision to Hindsight, on a human yes |
| `POST` | `/api/biz/history/resolve` | records what actually happened, closing the loop |

Two properties of this path are enforced in code and covered by tests:

- **A prompt is recorded and vectorised, never retained.** Retaining happens in exactly two places, both in
  `prompt_history.py`: `/commit` (adding a decision) and `/resolve` (recording its outcome). Both are
  user-initiated endpoints. `record_and_crossref`, which runs automatically on every prompt, has no Hindsight
  import at all, so it cannot retain even by mistake. That is the whole guarantee: automatic work never
  writes to the decision bank.
- **Nothing is invented.** A decision still being weighed has no result, so drafting leaves `result` and
  `outcome` empty and the stored document says so in words. `outcome` is validated against
  `good | mixed | bad`; `domain` and `decision_type` are constrained to the corpus taxonomy, because an
  off-vocabulary label would still be stored but could never match a corpus record in the lookalike
  comparison, making the record unretrievable in practice.

`resolve` re-retains under the **same `document_id`**, which supersedes the earlier document rather than
adding a second one (measured: two retains with one id produce one document). Without this an added
decision would stay permanently result-less: recallable as context, but never able to count as evidence,
which is what the verdict is computed from.

Committing the same decision twice is refused, and adding one the history already contains returns `409`
with the match shown, because the ranker counts precedents and the same event twice would inflate the
proof count behind a verdict.

The legacy deploy path from the earlier pivot is still served alongside it:
`POST /api/assess`, `GET /api/presets`, `GET /api/metrics`, `POST /api/replay`, `POST /api/seed`,
`GET /api/bank`, `GET /api/ledger`, `GET /api/ground-truth`, `POST /api/consolidate`.

### Production guards (mode switch, rate limit, and what does not exist)

There are no accounts, so every visitor is anonymous. **One variable, `APP_MODE`, controls the whole guard
surface:**

| | `APP_MODE=prod` (default) | `APP_MODE=dev` |
|---|---|---|
| Endpoints that spend money or write the bank | **404** | reachable |
| Per-visitor rate limit | **on**, 10 per 24h | **off** |

One switch rather than several flags, because the dangerous state is getting it half right: enabling the
admin endpoints in production to seed once and forgetting to re-enable the limit. An unset or unrecognised
`APP_MODE` is treated as **prod**, so a typo tightens the system rather than opening it. `ADMIN_ENDPOINTS_ENABLED`
and `RATE_LIMIT_ENABLED` still exist as per-guard overrides and win over the mode when set.

**In production, the cost and write endpoints do not exist.** `POST /api/biz/seed` spends 72 paid extractions
in one unauthenticated request; `commit` and `resolve` write to the bank the product cites, so an anonymous
caller could pollute the evidence. Along with `consolidate`, `replay` and `health/llm`, these answer
**404, not 403**: a 403 confirms the path exists and is worth attacking.

**The per-visitor limit counts only the paths that do work:**

| Counted (costs allowance) | Free (never counted) |
|---|---|
| `POST /api/biz/redflag`, `/api/biz/redflag/stream` | every `GET`: `/health`, `/api/biz/prompts`, `/api/biz/history`, `/stats`, `/unresolved` |
| `POST /api/biz/history/draft`, `/commit`, `/resolve` | `POST /api/biz/history/recall` |
| `POST /api/assess` (legacy) | `OPTIONS` preflight |

Counting the free reads would exhaust a visitor's allowance during one page load, before they typed anything.
On refusal the API returns `429` with `reason: "contact_sales"`, and the frontend replaces the composer with
a contact gate rather than a retryable-looking error. The gate stops further prompts client-side as well: the
composer is removed and `ask` refuses, so a preset click cannot slip through. The header shows the remaining
allowance before the limit bites, so it reads as a known boundary rather than a surprise.

**The client address is the last entry of `X-Forwarded-For`**, which is the one Traefik appends. Taking the
first would be trivially spoofable, since a client controls the prefix.

**CORS is restricted to the web origin**, `https://premortem.lexcontra.com`, not `*`. With a wildcard, any
site's JavaScript could call this API from a visitor's browser and spend their allowance. Being precise:
**CORS is a browser control and does not stop `curl`.** It is not a substitute for the rate limit; it closes
a different hole.

**What this is not.** A determined caller can still send requests from many addresses, and the counter is
in-memory, so it resets when the container restarts and does not span replicas. It is sized to stop the
realistic case, a public URL being scraped and looped, not a distributed attacker. Closing that properly
means taking the API off the public internet and reaching it only through the web app on the compose network,
with the counters in a shared store.

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

`/health` reports `bank_id: bizdecisions`, a `banks` object of
`{business: bizdecisions, legacy_deploy: premortem}`, and a `prompt_store` block (`url_set`, plus `error`
only when the store is unreachable). The prompt store is local, so reporting it here cannot unroute the
deployment; a store that is down degrades cross-referencing, not the review.

## Setup

```bash
cp .env.example .env      # HINDSIGHT_API_KEY, OPENCODE_GO_API_KEY, NEXT_PUBLIC_API_BASE_URL
docker compose up --build # api :8000, web :3000, postgres (pgvector) internal only

# first run only: build the corpus, then WAIT for observations (they are a background job)
curl -X POST localhost:8000/api/biz/seed
python api/scripts/smoke.py --url http://localhost:8000
```

Three containers: `api`, `web`, and `postgres`, which is the prompt store. `postgres` uses the
`pgvector/pgvector:pg16` image and a named volume (`promptstore`), carries no published port, and is
reachable only on the compose network as `postgres`. The API waits for it to be healthy, but a store that is
down degrades cross-referencing rather than breaking the review: every function on that path returns empty
and logs, so the answer still streams.

Local dev without containers: `uvicorn app.main:app --reload` in `api/`, `npm run dev` in `web/`. You need a
Postgres with the `vector` extension and `PROMPT_DB_URL` pointing at it; without one the store reports
unavailable and the rest of the product works unchanged.

No Groq key, no OpenAI key. Hindsight runs on Vectorize Cloud; our own LLM calls go to **OpenCode Go**
(`deepseek-v4.1-flash`); classification and mode routing are local via **Laya** (ONNX int4, 275MB,
Apache-2.0, baked into the api image). Embeddings for the prompt store are local too
(`BAAI/bge-small-en-v1.5`, 384-dim, CPU), reusing the `torch` already in the image for Laya, so the
prompt store adds no ML dependency and no network call. `recall` costs no LLM at all, which is why the
replay and the metrics are free and reproducible.

Three checks worth running against any base URL:

```bash
python3 api/scripts/mode_check.py https://premortem-api.lexcontra.com          # mode contract, 9 messages
python3 api/scripts/conversation_check.py https://premortem-api.lexcontra.com  # follow-ups stay chat
python3 api/tests/test_prompt_store.py                                         # 23 checks, needs PROMPT_DB_URL
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
    app/prompts.py       <- the prompt store: schema, migrations, local embeddings
    app/prompt_history.py<- the commit gate, drafting, and the outcome loop
    tests/test_prompt_store.py <- store + lifecycle checks
  web/                   <- Next.js: the chat window
    components/add-decision.tsx     <- capture a decision, pre-drafted from the review
    components/commit-prompt.tsx    <- the offer, plus the cross-reference
    components/resolve-decisions.tsx<- record what actually happened
  docker-compose.yml     <- api + web + postgres (pgvector); Hindsight and Laya are external/baked
```

## Scope, stated plainly

Decision support only. It reports what happened in your own history, with citations. It does not make the
decision, does not file anything, and does not give legal, tax, or financial advice. Synthetic data only.
