# Architecture

Technical spec for `pre-mortem`. Four modules, one Hindsight bank, one Streamlit screen.
Every API call below was verified against the installed `hindsight-client` SDK (introspected signatures),
not copied from docs.

## 1. Runtime shape

```
seed.py ──retain_batch──▶ Hindsight bank "premortem"
                             │  observations auto-consolidate after retain
                             │  client.banks.recover_consolidation() forces it before recording
                             ▼
app.py ──lookalike.assess(pending)──▶ recall + reflect ──▶ precedent cards + flip detail
     │
     └──ledger.summary()──▶ reorders what the agent leads with
```

No server, no DB, no job queue. `streamlit run app.py` is the whole app.

## 2. Module contracts

### `seed.py`

```python
LAUNCHES: list[dict]        # 40 records, defined in docs/DATA.md
PENDING:  list[dict]        # 3 demo changes, one has no precedent

def launch_text(l: dict) -> str
def seed(reset: bool = True) -> None
    """Idempotent. reset=True: delete_bank + create_or_update_bank.
       retain_batch(items=[{content, context, metadata, timestamp}], retain_async=False)
       then recover_consolidation(bank_id), then assert observations exist."""

def verify() -> dict
    """get_agent_stats(bank_id) + counts by fact type via recall(types=[...]).
       Prints: world/experience/observation counts, observation proof counts."""
```

`metadata` per launch (the cross-cutting keys, no bank explosion needed):

```python
{"launch_id": "L-2026-0412", "service": "payments-service",
 "change_class": "config-only", "pattern_id": "P1", "outcome": "incident"}
```

### `lookalike.py`

```python
def recall_precedents(pending: dict, k: int = 6, ts: str | None = None) -> list[Memory]
    """recall(bank_id, query=query_for(pending), types=["world","experience","observation"],
              budget="mid", max_tokens=1500, include_chunks=True, include_entities=True,
              query_timestamp=ts)"""

def rank(precedents, prefer: list[str] | None = None) -> list[Memory]
    """Deterministic. score = proof_count * 2 + recency_weight - trend_penalty
       - 2 if trend in ("weakening","stale"), +3 if observation is in prefer (ledger classes).
       Kept in this file, shown in the UI. No LLM in the ranking."""

def extract_flip(pending, precedents) -> dict
    """One reflect(bank_id, query=..., context=<assembled precedents>, budget="low",
       response_schema=FLIP_SCHEMA, include_facts=True).
       Returns {precedent_launch_id, differentiating_detail, why_it_matters, cited_fix}."""

def assess(pending, memory: bool = True, ts: str | None = None) -> dict
    """memory=False skips recall entirely and does one Groq call on the diff alone.
       Returns {risk, confidence, precedents, flip_detail, no_precedent, facts_used}."""

def run_memory_off(pending) -> str
    """Baseline for the demo contrast: same diff, no memories, generic output."""
```

`FLIP_SCHEMA` (passed to `reflect(response_schema=...)`):

```json
{"type": "object",
 "required": ["precedent_launch_id", "differentiating_detail"],
 "properties": {
   "precedent_launch_id": {"type": "string"},
   "differentiating_detail": {"type": "string",
     "description": "the one parameter difference between the precedent and the pending change that flips the outcome"},
   "why_it_matters": {"type": "string"},
   "cited_fix": {"type": "string",
     "description": "the fix that resolved the incident, quoted from memory"},
   "no_precedent": {"type": "boolean"}}}
```

`no_precedent` rule: if `rank()` returns nothing above `MIN_PROOF = 1`, or the top precedent's
`change_class + service` pair never appears in memory, return

```python
{"risk": "unknown", "no_precedent": True,
 "message": "No precedent for this shape of change. Coverage: 79% of past incidents had one.",
 "nearest": [<2 insufficient precedents>]}
```

The nearest-but-insufficient list is deliberate: it shows what it looked at and why it declined.

### `ledger.py`

```python
def record_flag(launch_id: str, flag: str, ignored: bool) -> None
    """retain(bank_id, content=f"FLAG {launch_id}: {flag}. ignored={ignored}.",
              metadata={"kind":"flag","launch_id":launch_id,"ignored":str(ignored).lower()})"""

def record_cost(launch_id: str, costed: bool) -> None
def ignored_classes() -> list[str]
    """recall(query="flags I dismissed that cost an incident", types=["observation","experience"])
       -> change classes to promote in rank()."""

def summary() -> dict
    """{flags: 4, ignored: 4, costed: 2, promoted_classes: ["config-only"]}"""
```

The ledger is seeded for days 1..n so the replay shows it accumulating, and it feeds `rank()`
through `prefer=`, which is why the same query returns a different ordering once a class is promoted.

### `app.py`

```python
# layout
st.sidebar : MEMORY=on/off toggle · ledger summary · bank stats (get_agent_stats)
             · "show the prompt" button (preview_prompt) · "force consolidation" (recover_consolidation)
col_left   : pending change selector (3 presets: P1-match, P3-match, no-precedent) + raw diff
col_right  : precedent cards -> launch_id, date, service, change_class, proof_count,
             trend badge, outcome, source chunk (collapsible)
top        : risk banner (high / medium / none / unknown) + confidence number
bottom     : flip detail sentence + cited fix + the "difference" wording
```

Two Streamlit buttons that carry the whole credibility story:

```python
# 1. show the literal prompt Hindsight assembles for this bank
preview_prompt(bank_id, PromptPreviewRequest(query=<pending>, ...))
# 2. force observation consolidation if the demo box was seeded minutes ago
recover_consolidation(bank_id)
```

`preview_prompt` is the strongest anti-black-box artifact in the project: the judge sees the mission,
directives, disposition, and the recalled memories literally pasted into the prompt. Nothing is hidden.

## 3. Hindsight surface used (verified signatures)

| Call | Used for |
|---|---|
| `Hindsight(base_url, api_key, timeout, max_attempts)` | client init, `max_attempts` gives free retries |
| `retain(bank_id, content, context, timestamp, metadata, tags, retain_async)` | one launch record; `timestamp` = the launch date so temporal recall and `query_timestamp` are honest |
| `retain_batch(bank_id, items, retain_async)` | the 40-launch seed in one call |
| `recall(bank_id, query, types, budget, max_tokens, query_timestamp, include_chunks, include_entities, prefer_observations, min_scores)` | precedent retrieval, gated by proof counts |
| `reflect(bank_id, query, budget, context, response_schema, include_facts, apply_all_directives)` | flip-detail extraction, structured, with `based_on` citation list |
| `banks.create_or_update_bank(bank_id, CreateBankRequest)` | bank with mission, directives, disposition |
| `banks.get_bank_config(bank_id)` | display the config in the UI (proof the guardrails are real) |
| `banks.recover_consolidation(bank_id)` | force observations to exist before recording |
| `banks.clear_observations(bank_id)` | reset during development without deleting the corpus |
| `banks.get_agent_stats(bank_id, refresh=True)` | bank stats panel |
| `banks.get_memories_timeseries(bank_id, period, time_field="occurred_start")` | **real** memory-growth chart, from actual counts, not synthesized |
| `banks.preview_prompt(bank_id, PromptPreviewRequest)` | show the assembled prompt |
| `banks.test_bank_llm(bank_id)` | pre-record health check, fails fast if the bank's LLM is unreachable |
| `banks.list_banks`, `directives`, `mental_models`, `entities`, `documents` | available; only `mental_models` is used (2 canned demo answers) |

`get_memories_timeseries` with `time_field="occurred_start"` deserves calling out: it buckets by event
time, so the growth chart reflects the launch timeline (14 months), not the ingest timestamp (today).
That is what makes the "memory filling up" visual honest.

## 4. Prompts

**`lookalike` flip extraction** — `reflect` supplies identity from the bank config, so the query only
carries the task:

```
Pending change on {service}:
{change_class}: {diff_summary}
Metrics before: {metrics}

Compared with the recalled precedents, name the ONE detail that differs between this change and the
precedent that broke. Use only recalled memories. Cite the launch ID. If no precedent applies, set
no_precedent=true.
```

**Bank `mission`**

```
I am a change-risk pre-mortem agent. I recall what this organization's own past launches did, and I
argue from precedent. I never assert a cause I cannot cite to a launch ID.
```

**Bank `directives`** (enforced strictly by reflect, violations rejected)

```
Never assert a precedent without citing a launch ID.
Never state a root cause that is not linked to a retained fix.
Always report the count of precedents behind a claim, including when it is zero.
Never invent a similarity when no precedent matches; say no precedent instead.
Never give instructions to deploy, ship, or approve anything.
```

**Bank `disposition`** — skepticism 4, literalism 5, empathy 2. Literalism 5 is the load-bearing trait:
it makes the agent read the diff exactly as written and refuse to infer intent, which is exactly the
behaviour a pre-mortem needs.

**Baseline (memory off)** — one Groq call, no Hindsight:

```
You are reviewing a software change for risk. No historical data is available.
Give a short risk review.
```

## 5. Metrics pipeline (`docs/DATA.md` holds the corpus; this is how they are computed)

```python
def replay(launches) -> list[dict]:
    """Honest, reproducible, and the source of the frozen demo numbers.
    For each launch i in date order:
      ts = launches[i].timestamp
      pred = lookalike.assess(pending=launches[i], ts=ts)   # query_timestamp = ts
      materialised = launches[i].outcome in ("degraded", "incident")
      record(predicted_high=pred.risk == "high", materialised=..., had_precedent=not pred.no_precedent)
    Returns per-launch rows; bucket into epochs (1-10, 11-20, 21-30, 31-40)."""

precision = predicted_high_and_materialised / predicted_high
coverage  = materialised_with_precedent / materialised
```

`query_timestamp=ts` is the whole reason these numbers are defensible: the pre-mortem for launch 40
cannot see launch 40. A judge can re-run `replay()` and get the same numbers, because the corpus is
static and the LLM is only used for the flip sentence, never for the prediction.

## 6. Failure handling

| Failure | Handling |
|---|---|
| Groq call fails or returns bad JSON | try/except, validate against schema, one repair retry, then plain JSON-mode fallback; on second failure show "flip detail unavailable" rather than a broken card |
| No precedent found | `no_precedent` state with coverage % and the two nearest insufficient precedents |
| Contradictory precedents (one broke, one near-identical did not) | both rendered side by side; risk is `medium` and the card states why; never averaged |
| Observations not consolidated | `recover_consolidation()` button and call at seed time; and reflect re-verifies stale observations against raw facts anyway |
| Bank unreachable / bad key | `test_bank_llm()` at startup, prints a clear error before the UI renders |
| Rate limited mid-replay | `max_attempts=3` on the client, small `max_tokens`, and the replay is pre-run and cached to JSON for recording |

## 7. Repo layout (target)

```
pre-mortem/
  README.md              # 5-year-old explainer + setup
  PLAN.md                # master plan, criteria mapping, SWOT, score guess
  docs/
    ARCHITECTURE.md      # this file
    DATA.md              # 40-launch corpus, patterns, ground truth
    DEMO.md              # 60s script, video beats, content deliverables
    CHECKLIST.md         # pre-record + submission checklist
  seed.py
  lookalike.py
  ledger.py
  app.py
  tests/run_all.py       # assert-based, no framework
  data/ground_truth.json # generated by seed.py, drives the metrics
```

## 8. Non-goals, permanent

No live deploys. No CI integration. No GitHub API. No auth. No database. No second use case.
No real customer data. The agent reports history; it never acts.
