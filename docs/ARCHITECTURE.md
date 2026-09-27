# Architecture

Technical spec for `pre-mortem`. Two deployables (FastAPI backend, Next.js frontend), one Hindsight
instance, one LLM provider (9Router). Every Hindsight API call below was verified by introspecting the
installed `hindsight-client` SDK; every 9Router behaviour was verified by calling it. Model and deployment
choices live in `MODELS.md`.

## 1. Why the UI is separate

The UI carries 15% of the score and the demo *is* the UI. Splitting it means:

- The frontend is pure presentation, so it can be made genuinely good (tailwind tokens, Framer Motion
  transitions on the replay, proper typography) instead of fighting a Python layout engine.
- The API owns memory and can be tested without a browser (fast, headless, assert-based).
- Judges can be given the Control Plane UI on `:9999` for a memory-side view, and the product UI on `:3000`,
  and they are clearly different things.
- The replay and metrics are precomputed server-side, so the UI stays instant during recording.

## 2. Topology

```
browser ──▶ Next.js :3000 ──/api/*──▶ FastAPI :8000 ──▶ Hindsight :8888 ──▶ 9Router (/v1)
                  │                        │                                    LLM + embeddings
                  │                        ├── flip-detail call also goes to 9Router
                  │                        └── owns seeding, replay, metrics, ledger
                  └── Hindsight Control Plane :9999 (judges only, not the product)
```

Hard rules:
- The browser **never** talks to Hindsight. All memory access is behind FastAPI, so there is one contract
  and one place to cache.
- FastAPI is the only writer to Hindsight.
- `NEXT_PUBLIC_API_BASE_URL` is the single coupling between the two.

## 3. Backend — FastAPI

```
api/
  app/
    main.py            FastAPI app, CORS, startup health check
    config.py          env loading, llm model + fallback, MIN_PROOF
    hindsight.py       client factory, bank bootstrap, consolidate, stats, timeseries, prompt preview
    corpus.py          the 40 launches + 3 presets, from DATA.md
    seed.py            idempotent seed + ground_truth.json writer
    lookalike.py       recall_precedents, rank (deterministic), extract_flip (LLM), assess
    ledger.py          flags, ignored outcomes, promoted classes, summary
    replay.py          honest epoch-wise replay -> replay.json
    models.py          pydantic request/response models
  scripts/smoke.py     pre-build + pre-record verification, must pass before app work
  tests/test_*.py      pytest, no framework beyond pytest
```

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Hindsight reachable, bank config readable, model name, `test_bank_llm` result |
| `GET` | `/api/bank` | agent stats, bank config (mission/directives/disposition), memories timeseries |
| `POST` | `/api/seed` | idempotent: recreate bank, retain 40 launches, force consolidation, write ground truth |
| `POST` | `/api/consolidate` | `recover_consolidation`; used right before recording |
| `GET` | `/api/presets` | the 3 pending changes (A: P1 match, B: P3 match, C: no precedent) |
| `POST` | `/api/assess` | `{preset_id or pending, memory: bool, engine: "recall"\|"reflect"}` -> `Assessment`. `recall` is the default (no LLM cost); `reflect` is the showcase path |
| `GET` | `/api/ledger` | flags, ignored counts, promoted classes |
| `POST` | `/api/ledger/flag` | record a flag as ignored/actioned (drives promotion) |
| `POST` | `/api/replay` | run the epoch replay, cache to `data/replay.json` |
| `GET` | `/api/metrics` | cached precision/coverage by epoch + derivable-vs-found coverage |
| `GET` | `/api/prompt-preview` | `preview_prompt` passthrough: the literal assembled prompt |

### `Assessment` contract (frozen before frontend work starts)

```json
{
  "memory": true,
  "risk": "high",
  "confidence": 0.86,
  "no_precedent": false,
  "coverage": 0.79,
  "precedents": [{
    "launch_id": "L-2026-0412", "date": "2026-03-14", "service": "payments-service",
    "change_class": "config-only", "proof_count": 2, "trend": "strengthening",
    "outcome": "incident", "score": 7.4, "memory_id": "…", "source_chunk": "HikariPool-1 …"
  }],
  "flip": {
    "precedent_launch_id": "L-2026-0412",
    "differentiating_detail": "max_overflow was raised in the same commit; yours does not",
    "why_it_matters": "…", "cited_fix": "raise max_overflow to 20 and set pool_pre_ping=true"
  },
  "declined": [{"launch_id": "…", "reason": "different service, no shared mechanism", "proof_count": 0}],
  "ledger_promoted": ["config-only@payments-service"],
  "facts_used": ["…"],
  "engine": {"ranker": "deterministic", "llm": "gareebi", "llm_calls": 1}
}
```

`engine.llm_calls` is on the wire on purpose: it proves the verdict came from the ranker and the LLM only
wrote the sentence. The UI renders it.

### Ranking, deterministic and shown

```python
def rank(precedents, prefer):
    # score = proof*2 + recency_weight - trend_penalty + ledger_boost
    # proof*2            : evidence beats everything
    # recency_weight     : newer precedents first, 1.0 -> 0.2 across the window
    # -2                 : trend in ("weakening","stale")
    # +3                 : class in prefer (ledger-promoted)
    # No LLM. Exposed at GET /api/assess?debug=rank and rendered in the UI.
```

Gating: nothing below `MIN_PROOF` (default 1; raise to 2 once the corpus is fresh) may be shown as a
precedent. If nothing clears the bar in the relevant `service + change_class`, return `no_precedent` with
`coverage` and up to 2 `declined` entries carrying a reason.

### LLM usage in the backend (OpenCode Go primary, 9Router fallback)

Every chat call sends `x-opencode-session: $OPENCODE_SESSION` (a stable per-run string). OpenCode Go rejects
chat without it (`MissingSessionID`), so this is a hard requirement, not an optimisation.

Verified on `deepseek-v4-flash`: chat, auto tool calling, forced tool calling, JSON mode, and multi-turn
`role:"tool"` loops all work. Hindsight's `reflect` drives forced tool calling internally, so the smoke test
is expected to pass on the first try.

| Call | Shape | Why |
|---|---|---|
| Flip-detail extraction | `{"model","messages","response_format":{"type":"json_object"}}`, schema echoed in the prompt | JSON mode is the portable path across both providers |
| Memory-off baseline | same, no memories in prompt | the contrast beat |
| Repair | one retry with a forced `tool_choice: {"type":"function",...}` | verified working on both providers if JSON mode ever misbehaves |
| Provider fallback | `LLM_FALLBACK_MODEL=gareebi` on 9Router, `NINEROUTER_*` env | keeps the demo alive if the primary lane misbehaves |

Hindsight's own retain/reflect calls use the **native `opencode-go` provider** (`HINDSIGHT_API_LLM_PROVIDER`
+ `HINDSIGHT_API_LLM_MODEL`). `reflect` drives forced tool calling internally, which is why the pre-build
smoke test must exercise `reflect` with `response_schema` before any app code is written: a provider that
ignores forced tools breaks reflect while retain keeps working, which would fail late and confusingly.

## 4. Frontend — Next.js App Router

```
web/
  app/
    layout.tsx        fonts, tokens
    page.tsx          the one screen
    globals.css       design tokens + @theme inline
  components/
    ChangePanel.tsx   preset selector + diff view
    MemoryToggle.tsx  MEMORY on/off
    RiskBanner.tsx    high / medium / none / unknown + confidence
    PrecedentList.tsx ranked cards
    PrecedentCard.tsx launch id, date, service, proof count, trend badge, outcome, source chunk
    FlipDetail.tsx    the differentiating detail + cited fix, emphasised
    DeclinedList.tsx  nearest-but-insufficient, with reasons (carries the no-precedent story)
    LedgerPanel.tsx   flags, ignored, costed, promoted classes
    MetricsPanel.tsx  precision/coverage by epoch, growth chart
    PromptPreview.tsx collapsible, the literal assembled prompt
    RankDebug.tsx     the scoring breakdown
  lib/api.ts          typed client for the contracts above
  test/               vitest + RTL
  e2e/                playwright smoke
```

Design intent, in priority order (we cannot win Innovation with polish, but we can lose UX without it):
1. **The flip detail is the hero.** Larger type, distinct surface, its own card. It is the single sentence
   that is not a similarity search.
2. **Every number is attributable.** Proof counts, launch IDs, and trend badges sit next to the claims, not
   in a footer. Hovering a citation highlights the fact it came from.
3. **The refusal state must look confident, not broken.** `no_precedent` gets the same visual weight as a
   risk card, with coverage and the declined list. Designed first, not last.
4. **Trend badges are the only colour signal.** Green/amber/red encodes only freshness trend, so colour
   always means the same thing.
5. **Replay is a slider with a chart, no animation cost.** Precompute frames from `replay.json`; the slider
   scrubs cached state so the frame rate can never embarrass us on camera.

## 5. Testing

| Layer | Tool | What is actually asserted |
|---|---|---|
| API unit | pytest | `rank()` is deterministic and order-stable; `MIN_PROOF` gate blocks low-proof precedents; ledger promotion changes preset A's top card; ground-truth totals match the corpus table; `no_precedent` fires for preset C |
| API integration | pytest | one real retain -> recall -> reflect round trip against Hindsight, skipped if `HINDSIGHT_API_URL` unset |
| UI unit | vitest + RTL | `RiskBanner` renders all four states; `PrecedentCard` renders citations; toggle swaps the request payload |
| E2E | Playwright | the three presets end to end, memory toggle changes the output, `no_precedent` state reachable |
| Pre-record | `scripts/smoke.py` | health, `test_bank_llm`, one observation with a proof count, `reflect` with `response_schema` |

CI runs typecheck, lint, pytest, vitest, build. Playwright runs where a browser is available; if it cannot
in a given environment, report which steps were verified locally rather than claiming a green gate.

## 6. Failure handling

| Failure | Handling |
|---|---|
| Hindsight unreachable | `/health` fails loudly at startup; the UI shows a clear connection error, no spinner-forever |
| Hindsight's LLM (9Router) erroring | `HINDSIGHT_API_LLM_MAX_RETRIES` + a longer `HINDSIGHT_API_LLM_TIMEOUT`; swap `HINDSIGHT_LLM_MODEL` to `ocg/deepseek-v4.1-flash` |
| Our JSON-mode call returns prose | detect a missing/unparsable body, retry once with a forced `tool_choice`, then `LLM_FALLBACK_MODEL`, then render "flip detail unavailable" rather than a broken card |
| Observations not consolidated | `POST /api/consolidate` button in the UI, and it runs at seed time; reflect re-verifies stale observations against raw facts regardless |
| Contradictory precedents | both rendered, risk `medium`, card states why; never averaged |
| Rate limit mid-replay | replay is precomputed and cached; the UI never triggers 40 live calls |
| Bad/missing env | `configProblems()` reported by `/health`; `next build` must not require runtime secrets |

## 7. Non-goals, permanent

No live deploys. No CI integration. No GitHub API. No auth. No database of our own (Hindsight owns the
memory). No second use case. No real customer data. Nothing in the product ships, approves, or advises.
