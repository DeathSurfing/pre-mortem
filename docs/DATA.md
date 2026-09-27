# Corpus — 40 interlocked launches

The corpus is the project. If it is not interlocked, nothing downstream works: no real similarity to find,
no flip detail to extract, no honest coverage numbers, no contradiction to show.

Everything here is synthetic. No employer data, no customer data, no real incident reports.

## Generator parameters

```python
START      = date(2025, 7, 20)
STEP_DAYS  = 11                      # one launch every 11 days -> 40 launches = ~14 months
SERVICES   = ["payments-service", "auth-service", "search-index",
              "ingest-pipeline", "notification-worker", "billing-api"]
CLASSES    = ["config-only", "dependency-bump", "schema-migration",
              "flag-flip", "infra-change"]
```

Weight classes so config-only and dependency-bump dominate, which is realistic for pre-mortem purposes:
`config-only` (12), `dependency-bump` (10), `flag-flip` (8), `schema-migration` (6), `infra-change` (4).

Date of launch `i` = `START + timedelta(days=11*i)`, `i` from 0 to 39. Epochs for the metrics:
E1 = idx 0-9, E2 = 10-19, E3 = 20-29, E4 = 30-39.

## Failure patterns (the interlocks)

Each pattern has multiple instances so Hindsight's consolidation has material to work with, plus at least
one **clean mirror** — a near-identical launch that did not break. The clean mirrors are what makes
flip-detail extraction meaningful, and they are what a similarity search gets wrong.

| Pattern | Service | Class | Mechanism | Breaking instances (idx) | Clean mirror (idx) |
|---|---|---|---|---|---|
| **P1** | payments-service | config-only | pool size changed alone, evicts nothing, pool exhausts under load | 4, 16, 31 | 25 — same change but `max_overflow` raised in the same commit |
| **P2** | auth-service | dependency-bump | JWT library minor bump changes signature defaults | 7, 21 | 34 — same bump but version pinned with `==` |
| **P3** | search-index | schema-migration | migration without pre-backfill stalls the read replica | 2, 13, 27 | 37 — same migration but backfill pre-ran and throttle set |
| **P4** | ingest-pipeline | config-only | batch size raised without memory headroom | 9, 24 | 18 — batch reduced deliberately with profiling |
| **P5** | notification-worker | flag-flip | retry flag doubled with provider-side idempotency missing | 11, 29 | 22 — flag flipped after idempotency key shipped |
| **P6** | billing-api | schema-migration | rounding mode changes silently with a decimal column migration | 19 | 6 — same class, unrelated column, no rounding path |

### Fixes recorded per pattern (the "cited fix" the agent must quote)

| Pattern | Fix that resolved it |
|---|---|
| P1 | raise `max_overflow` to 20 and set `pool_pre_ping=true`; the pool was sized without headroom for the p99 burst path |
| P2 | pin the JWT library to the previous minor, then adopt the new default only alongside the `HS256` migration |
| P3 | run the backfill job to completion before the migration, throttle replica reads during it |
| P4 | revert batch size, add a memory profiler to CI, cap at the profiled ceiling |
| P5 | ship the provider idempotency key first, then re-enable the retry flag |
| P6 | pin the rounding mode explicitly in the migration, add a decimal-delta assertion test |

## Outcomes

13 of 40 launches materialise: 8 `incident`, 5 `degraded`, 22 `clean`. Incidence is deliberately ~33% —
high enough that the flags are not rare, low enough that precision is a real question.

## Symptom lines (real-shaped, this is what sells the corpus)

```
P1 payments-service
  p99 latency 210ms -> 1.9s
  HikariPool-1 - Connection is not available, request timed out after 30000ms
  (total=20, active=20, idle=0, waiting=83)

P2 auth-service
  401 rate 0.02% -> 4.1%
  jwt.exceptions.InvalidSignatureError: Signature verification failed

P3 search-index
  replica lag 0.4s -> 47s
  stale_doc_ratio 0.7% -> 12.4%

P4 ingest-pipeline
  OOMKilled (container ingest-worker, peak_rss 1.8Gi / limit 1.5Gi)
  consumer lag 1.2k -> 340k messages

P5 notification-worker
  duplicate_send_rate 0.1% -> 6.3%
  provider 429 bursts, no idempotency key on retry path

P6 billing-api
  avg invoice_total_delta +0.43%
  rounding mode changed half-up -> half-even in the decimal migration
```

## Retained record shape (one per launch)

```python
{
  "content": """Launch L-2026-0412 | payments-service | config-only
    Change: reduced connection pool size 40 -> 20, no other parameter touched.
    Diff: application.yml: hikari.pool-size 40 -> 20
    Symptom: p99 latency 210ms -> 1.9s. HikariPool-1 Connection is not available,
      request timed out after 30000ms (total=20, active=20, idle=0, waiting=83).
    Outcome: incident (sev2, 46min).
    Fix applied: raised max_overflow to 20 and set pool_pre_ping=true;
      pool was sized without headroom for the p99 burst path.
    Note: the identical pool change in L-2025-XXXX shipped clean because
      max_overflow was raised in the same commit.""",
  "context": "post-deploy change record",
  "timestamp": <launch datetime>,
  "metadata": {"launch_id": "L-2026-0412", "service": "payments-service",
               "change_class": "config-only", "pattern_id": "P1", "outcome": "incident"}
}
```

Two deliberate details:
- **The clean mirror is written into the breaking record's text.** That is what gives the flip-detail
  extraction something to find without the agent having to guess, and it is realistic: postmortems do
  reference the clean case.
- `timestamp` is the launch date, not today. Combined with `query_timestamp` in replay and
  `time_field="occurred_start"` in `get_memories_timeseries`, the whole timeline stays honest.

## Ignored-warning ledger seed

Flags recorded during the replay, so the ledger has a history by the demo:

| Launch idx | Flag raised | Ignored? | Cost |
|---|---|---|---|
| idx 4 (P1 payments) | config-only pool change on payments | yes | incident |
| 9 (P4 ingest) | batch size raised without profiling | yes | incident |
| 16 (P1 payments) | config-only pool change on payments | no | — (actioned, no incident) |
| 13 (P3 search) | schema migration without pre-backfill | yes | no incident that time |

Result: 4 flags, 3 ignored, 2 of the ignored ones cost an incident, and the promoted class is
`config-only` on `payments-service`. Promoting that class changes `rank()` on the demo query — the same
question returns a different top result once the ledger has history. That is the learning beat.

## Ground truth (what makes the metrics falsifiable)

`seed.py` writes `data/ground_truth.json`. It is computed from this table, **not** from the LLM:

```python
{
  "launches": [
    {"launch_id": "...", "date": "...", "service": "...", "change_class": "...",
     "pattern_id": "P1", "materialised": true,
     "precedent_derivable": true,     # a prior launch in the same pattern_id exists
     "precedent_launch_id": "..."}    # that prior launch, or null
  ],
  "totals": {"launches": 40, "materialised": 13, "materialised_with_prior": 9}
}
```

Two coverage numbers get reported, and the difference between them is the honest bit:

```
derivable coverage  = materialised_with_prior / materialised            # corpus ceiling
found coverage      = materialised where the agent actually cited one   # agent performance
```

If the agent only finds 6 of the 9 derivable ones, say so on screen. Hiding that gap is the fastest way
to lose a technical judge.

## Target metric bands and the tuning knobs

Design targets, not promises. After the first full `replay()`, **freeze the actual numbers**; if they fall
outside the band, tune the knob, do not tune the write-up.

| Metric | Target | Knob |
|---|---|---|
| Flag precision, E1 -> E4 | 64% -> 88% | `MIN_PROOF` in `rank()`, pattern specificity in the queries |
| Coverage, E1 -> E4 | 31% -> 79% | corpus density per pattern (add instances to E3/E4), `budget` in recall |
| `no_precedent` rate | high in E1, near zero by E4 | `MIN_PROOF`; too high and it refuses everything, too low and it stretches |
| Flag recall on the ledger classes | 100% after promotion | `prefer=` weight in `rank()` |

## Demo presets (three pending changes in the UI)

| Preset | Pending change | Expected behaviour |
|---|---|---|
| **A — P1 match** | payments-service, config-only, reduce `pool-size` 40 -> 20, nothing else touched | 3 precedents including `L-2026-0412`, risk **high**, flip detail = "`max_overflow` was also raised last time; you have not raised it", cited fix = P1 fix |
| **B — P3 match** | search-index, schema-migration on a indexed column, backfill not scheduled | precedents cite the pre-backfill failures, risk **medium-high**, flip detail = "the clean case ran the backfill first; yours has none scheduled" |
| **C — no precedent** | infra-change, `notification-worker` region move, no parameter change | `no_precedent`; coverage stated; two nearest-but-insufficient precedents shown; risk **unknown** |

Preset A also demonstrates the ledger: with the ledger populated, the payments config-only class is
promoted, so A's card appears first and carries the "you were warned about this class twice" line.

Preset C is the one that matters most for the anti-black-box story. Rehearse it twice.

## Contradiction case (show it, do not hide it)

`L-2025-XXXX` (idx 25) is a clean mirror of P1: same pool change, but `max_overflow` raised together.
Show both records side by side on the P1 card. Risk stays `medium`, the card states why it is not `high`,
and the agent never averages the two into a comforting middle. Judges remember the case where the agent
argued both sides.
