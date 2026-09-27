# pre-mortem

> Flag a business decision before you make it, from what your company already learned.

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

## The grown-up version

You type a decision. The reviewer comes back with:

- a **verdict** derived from what actually happened to your past decisions, not from an opinion,
- the **precedents**, each cited by id with how much evidence stands behind it,
- the **difference**: the one detail that separated a past decision that went badly from a
  near-identical one that went fine,
- the **guardrail**: the specific condition, taken from your own recorded lessons, that would make it safe,
- **open questions** to answer before deciding,
- and a refusal (`no precedent`) when your history does not cover it.

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

## Where Laya fits (and where it does not)

Laya is a **System One model**: it does not write text, it evaluates a state and returns typed answers with
calibrated probabilities. It runs locally, offline, Apache-2.0.

It replaces the classification call that used to cost an LLM request, and adds two signals an LLM never
gave us:

```
choice -> domain (pricing / hiring / vendor / …)   measured 0.9487 / 0.9981 / 0.9423, all correct
score  -> reversibility (Easy / Moderate / Hard)
noul   -> whether value is being given away for nothing, and blast radius
```

Laya's own authors report **67.3% vs 59.6%** on 108 hand-labelled cases. That is a real but modest edge on
a small sample, so Laya is used where a calibrated probability is genuinely useful and a mistake is cheap:
classification and gating. **The verdict is never produced by a model.** Four separate jobs, no overlap:

```
Laya classifies  ->  Hindsight remembers  ->  the ranker decides  ->  the LLM writes prose
```

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
(`deepseek-v4.1-flash`); classification is local via **Laya** (ONNX int4, baked into the api image).
`recall` costs no LLM at all, which is why the replay and the metrics are free and reproducible.

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
