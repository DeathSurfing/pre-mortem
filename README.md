# pre-mortem

> Your deploy history, argued back at you before you ship.

An agent that remembers every change your org has shipped, what it broke, and **the one detail that flipped
the outcome** — so the next deploy starts from precedent instead of optimism.

Built for the *AI Agents That Learn Using Hindsight* hackathon. Memory layer: [Hindsight](https://hindsight.vectorize.io/).

---

## The idea, explained like you're 5

Imagine you build towers with blocks. Sometimes a tower falls down.

Every time a tower falls, a robot writes down *why* in a notebook. "Fell down because I put the heavy block
on top." "Fell because the bottom was wobbly."

Now you want to build a new tower. Before you start, the robot looks in its notebook and says:

> "Hey. A tower like this one fell down 2 times before. Both times the heavy block was on top.
> So put the heavy block at the bottom this time."

That's the whole idea.

Two more bits:

1. **The robot remembers when you didn't listen.** "I told you 4 times the heavy block breaks it. You did it
   anyway 2 times, and it broke both times. So now I say it first and I say it louder."
2. **If you build a tower it has never seen, it doesn't make something up.** It says: *"I don't know this
   one. I've never seen it fall. Be careful."*

Saying "I don't know" is the important part. That's what makes it not a liar.

*(This section is the script seed for the demo video. Keep it. It is the 20-second cold open.)*

---

## The grown-up version

Before you deploy a change, the agent tells you about the last times your org shipped something that looked
exactly like this, and what happened. Not a generic checklist — a memory of your own change history, with:

- the **precedent cited by launch ID and date**,
- the **one differentiating detail** that flipped the outcome last time
  ("you also changed only the pool size, latency p99 spiked 4x, root cause was `max_overflow`"),
- **confidence taken from proof counts**, not a hand-tuned score,
- a **trend badge** when a failure mode is getting worse or fading,
- and an honest **`no_precedent`** answer when there is nothing to learn from yet.

Then it remembers which of its own warnings you ignored, and what that cost — and changes what it leads with.

## Why this shape

| | Typical hackathon agent | pre-mortem |
|---|---|---|
| Memory object | users, chats, tickets | your org's own shipped changes |
| Direction | backwards-looking retrieval | prospective: argues about a change not yet shipped |
| Output | an answer | a cited precedent, a difference, and a risk count |
| Contribution | RAG over a corpus | lookalike retrieval + **flip-detail extraction** + ignored-warning ledger |
| Failure mode | hallucinated confidence | says `no_precedent` and stops |

## How Hindsight is used

Memory is not a feature here, it is the entire artifact. Remove Hindsight and there is no corpus, no
confidence number, no trend, no calibration, and no way to prove the replay is honest.

| Piece of the product | Hindsight surface |
|---|---|
| Launch history (diff summary, metrics, outcome, fix) | `retain` with `metadata` = launch ID / service / change class |
| Consolidated across launches: *"config-only payments deploys broke twice, both times a pool parameter (proof 2, strengthening)"* | `observation` with proof count + freshness trend |
| The confidence number in the UI | observation proof count, no hand-tuning |
| "This failure mode is getting worse" badge | freshness trend: `strengthening` / `weakening` / `stale` |
| Precedent cards with exact source | `recall(include_chunks=True)` |
| Honest replay (a pre-mortem for launch N cannot see launch N+1) | staged ingestion + our own `occurred_start` filter. Measured: `query_timestamp` does **not** filter on API 0.10.1 |
| Refusing to assert an uncited cause | `directives` ("never assert a precedent without a cited launch ID") |
| Refusing instead of guessing | `disposition` skepticism 4 / literalism 5 / empathy 2 |
| Instant, identical canned demo answers | `mental_models` |
| Forcing observations to exist before recording | `banks.recover_consolidation()` |
| Showing the literal assembled prompt (mission + directives + disposition + recalled facts) | `banks.preview_prompt()` |
| A real memory-growth chart, bucketed by event time not ingest time | `banks.get_memories_timeseries(time_field="occurred_start")` |
| Pre-record health check on the bank's LLM | `banks.test_bank_llm()` |

## The two numbers that make the learning claim falsifiable

```
Flag precision (of risks flagged, how many materialised)     64% -> 88% across the replay
Coverage (share of real incidents with a matching precedent)  31% -> 79%
```

Plus the honest one: the cold-start bucket (incidents with no precedent) starts high and falls as the
memory fills. Reporting it is the point.

## The ignored-warning ledger

The agent retains the flags you dismissed, and what each dismissal cost. Then it leads with that class of
warning. Four flags ignored, two of which cost an incident, means the next one of that class is the first
thing on screen.

## Build plan (5 hours, two tiers)

| Time | Work |
|---|---|
| 0:00-0:50 | Hindsight up on 9Router, `api/scripts/smoke.py` green: health, `test_bank_llm`, retain → recall → `reflect(response_schema)`. **Gate: no app code until this passes** |
| 0:50-1:50 | `api/`: 40 interlocked launches, retain with metadata, force consolidation, `ground_truth.json` |
| 1:50-2:35 | `api/`: recall (no LLM) + `occurred_start` filter, deterministic rank, flip-detail via OpenCode Go JSON mode, `no_precedent` path |
| 2:35-3:00 | `api/`: ignored-warning ledger, epoch replay cached, `/api/metrics` |
| 3:00-4:20 | `web/`: the one screen — change panel, memory toggle, risk banner, precedent cards with citations, **flip detail as the hero**, declined list, ledger, metrics |
| 4:20-4:40 | Bank `mission` / `directives` / `disposition`, 2 `mental_models`, three presets end to end, freeze the numbers, raw screen capture |
| 4:40-5:00 | `/health`, compose wiring, `.env.example`, README |

**Never cut:** the `MEMORY=on/off` toggle, proof counts as confidence, the `no_precedent` refusal, the
flip-detail line, the ignored-warning ledger. Everything else is decoration.

## Demo script (60 seconds)

1. **0-12s** Memory off. Paste a pending config-only change to `payments-service`. Generic answer:
   "review for risk, ensure rollback plan, monitor metrics." Nothing checkable.
2. **12-30s** Memory on, same change. Three precedents with launch IDs and dates. Top result: `L-2026-0412`,
   majority detail — you also changed only the pool size, p99 spiked 4x, root cause `max_overflow`
   (proof 2, `strengthening`). One sentence: *"last time this exact shape of change broke this service."*
3. **30-42s** The **flip detail**: the one parameter difference between then and now that changes the
   outcome, citing the fix that resolved it. Say the word "difference", not "similar".
4. **42-52s** Ask about a change with no precedent. The agent returns `no_precedent`, states its coverage,
   and refuses to stretch an analogy.
5. **52-60s** Counters: precision and coverage climbing, trend badges on two services, and the
   ignored-warning ledger: "you were warned 4 times, 2 cost incidents, so I lead with this class now."

## Data

Synthetic, fully controlled, and it must be **interlocked** or nothing else works: config-only payments
deploys breaking on pool parameters, schema migrations causing read-replica lag, dependency bumps breaking
auth. 40 launches, 6 services, ~14 months, real-sounding service names and real-shaped symptom lines.

## Repo layout

```
pre-mortem/
  README.md              <- this file (5-year-old explainer lives here for the video)
  PLAN.md                <- master plan: criteria mapping, SWOT, metrics, risks
  docs/
    ARCHITECTURE.md      <- topology, API contracts, ranking, failure handling
    MODELS.md            <- 9Router + self-hosted Hindsight, verified behaviour, fallbacks
    DATA.md              <- the 40-launch corpus, 6 interlocked patterns, ground truth
    DEMO.md              <- 3min video script, shot list, article + social outline
    CHECKLIST.md         <- day-1 build, pre-record, submission gates
  api/                   <- FastAPI: owns Hindsight, seeding, ranking, replay, metrics
  web/                   <- Next.js: the one screen (this is what judges watch)
  docker-compose.yml     <- hindsight + api + web
```

Start with `docs/ARCHITECTURE.md` and `docs/DATA.md`; they fix every decision the build depends on.

## Setup

```bash
cp .env.example .env      # HINDSIGHT_API_KEY, OPENCODE_GO_API_KEY, NEXT_PUBLIC_API_BASE_URL
docker compose up --build # api :8000, web :3000

# first run only: build the corpus, then WAIT for observations (they are a background job)
curl -X POST localhost:8000/api/seed
python api/scripts/smoke.py --url http://localhost:8000 --llm
```

Local dev without containers: `uvicorn app.main:app --reload` in `api/`, `npm run dev` in `web/`.
Hindsight itself runs on Vectorize Cloud (`https://api.hindsight.vectorize.io`), so there is no memory
container to run.


No Groq key, no OpenAI key. Our LLM calls go to **OpenCode Go** (`deepseek-v4.1-flash`); Hindsight Cloud
does its own extraction with its own configured model. `recall` costs no LLM at all, which is why the
replay and the metrics are free and reproducible. Hindsight embeds
locally (`BAAI/bge-small-en-v1.5`), so there is no external embedding provider either.

Deployed on Dokploy: project `pre-mortem`, compose stack `hQJmXPzH4h31K6PNN9M5_`, built from this repo
through the `pre-mortem-Vikk` GitHub app. Push to `main` triggers a deploy.

| URL | Service |
|---|---|
| https://premortem.lexcontra.com | `web` (the demo UI) |
| https://premortem-api.lexcontra.com | `api` (FastAPI; `/health` is the readiness check) |

DNS for both hostnames must exist before the first deploy, or the Let's Encrypt challenge fails. Full
deploy sequence and the Dokploy traps are in `docs/MODELS.md`.

## Scope, stated plainly

This is a decision-support tool. It reports what happened in your change history, with citations. It does
not ship anything, does not touch production, and does not give advice. Synthetic data only.
