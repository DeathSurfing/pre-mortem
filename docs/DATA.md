# Corpus

Two corpora live in this repo. The **business corpus is the product**: 72 recorded business decisions that
the reviewer searches, and the only one the deployed UI reads. The **deploy corpus** (40 launches) is the
pivot leftover, still seeded into its own bank and still what the epoch replay runs against.

Everything here is synthetic. No employer data, no customer data, no real incident reports.

| | Business (the product) | Deploy (legacy) |
|---|---|---|
| Decisions / launches | 72 | 40 |
| Bank | `bizdecisions` | `premortem` |
| Recurring patterns | 10, ids `B1`-`B10` | 6, ids `P1`-`P6` |
| Clean mirrors | 11 | 6 |
| Prompts | 5, keys `A`-`E` | 3 deploy presets |
| Module | `api/app/bizcorpus.py` (+ `bizcorpus_extra.py`) | `api/app/corpus.py` |

# Part 1 — Business corpus (the product)

## Shape

```python
START     = datetime(2025, 2, 3)
STEP_DAYS = 14                      # one decision every 14 days -> 72 decisions = 2025-02-03 .. 2027-10-25
DOMAINS   = 10                      # pricing, hiring, marketing, vendor, launch, buildvsbuy,
                                    # compliance, security, partnership, ops
```

Decision ids are `D-<year>-<idx:04d>`, so `D-2025-0000` through `D-2027-0071`. Domain and decision type
come from a plan list; each entry is either a plain decision, a breaking instance (`brk`) or a clean mirror
(`mir`) of a pattern.

## Outcomes

| Outcome | Count |
|---|---|
| `good` | 47 |
| `bad` | 22 |
| `mixed` | 3 |
| **total** | **72** |

25 of the 72 carry a bad or mixed outcome, and 26 have a prior decision they could be compared against
(`precedent_derivable`). That is the number that makes coverage falsifiable: the corpus ceiling is 60%
(`materialised_with_prior` 15 / `materialised` 25), not 100%.

## Failure patterns (the interlocks)

Ten recurring decision shapes, each with several breaking instances and, where the story allows, at least one
**clean mirror**: a near-identical decision that went fine because of exactly one differing detail. The
mirror is what the difference step is extracted from, and what a similarity search gets wrong.

| Pattern | Domain / type | Mechanism | Breaking idx | Clean mirror idx |
|---|---|---|---|---|
| **B1** | pricing / discount | 30% renewal discount with no term change; the discounted price becomes the list price | 2, 13, 37 | 23, 54 — same discount, 3 year term commitment and a 250 seat floor |
| **B2** | hiring / senior-hire | senior hire at the top of band with the scope defined after they start | 7, 27, 47, 56 | 18 — same hire against a written 90 day mandate with a review gate |
| **B3** | vendor / vendor-switch | switch vendor on price alone, cut over at contract end | 5, 20, 31, 41, 58 | none |
| **B4** | marketing / budget-shift | move the paid budget to the best last click ROAS channel | 9, 33, 44, 60 | 21 — spend increase held against a small untargeted control group |
| **B5** | launch / feature-ga | launch to all customers on the same day | 11, 35, 50 | 25, 64 — 5 percent cohort first, with support staffing in place |
| **B6** | buildvsbuy / build | build in house because the build quote beat three years of licence | 16, 53 | 29 — same build with the maintenance burden priced and an exit plan written |
| **B7** | compliance / audit-finding | close an audit finding with a compensating control and defer the root-cause fix | 38 | 62 — same control with a named owner and a dated milestone in the audit response |
| **B8** | security / incident-response | treat a repeat dependency failure as an isolated incident and patch the symptom | 42 | 66 — same failure treated as systemic, replacement scheduled |
| **B9** | partnership / reseller-agreement | give a reseller segment exclusivity to close quickly | 45 | 68 — exclusivity with a volume floor and a 12 month review date |
| **B10** | ops / datacenter-region | stand up a region for two prospects with nothing signed | 49 | 70 — stand up against a signed letter of intent with a dated commitment |

Lessons recorded per pattern (what the review should surface as the guardrail):

| Pattern | Lesson |
|---|---|
| B1 | tie any discount to a term commitment or a volume floor, and log the margin delta at approval |
| B2 | write a 90 day mandate with named deliverables before opening the role |
| B3 | run the new vendor in parallel for one billing cycle and document every integration before cutting over |
| B4 | hold a small untargeted control group before scaling spend in any single channel |
| B5 | stage the rollout to a cohort with support staffing in place before general availability |
| B6 | price the maintenance burden over three years, not just the build, and write the exit plan |
| B7 | an interim control without a named owner and a dated milestone does not get remediated |
| B8 | a dependency that has failed twice will fail a third time; a surface patch only postpones it |
| B9 | exclusivity without a volume floor transfers all the optionality to the partner |
| B10 | wait for a signed commitment before committing infrastructure spend |

## Retained record shape (one per decision)

```python
{
  "content": """Business decision D-2025-0002 | pricing | discount
    Decided on: 2025-03-03
    Owner: ...
    Amount at stake: ...
    Context at the time: ...
    Decision: give Acme a 30 percent discount on the renewal to close it this quarter, no term change
    Rationale at the time: ...
    Result: Gross margin fell 6.2 points over two quarters. Three other accounts cited the same discount
      in their next renewal, so the discounted price became the de facto list price. ...
    Lesson recorded: tie any discount to a term commitment or a volume floor, and log the margin delta
      at approval""",
  "metadata": {"decision_id": "D-2025-0002", "domain": "pricing", "decision_type": "discount",
               "pattern_id": "B1", "outcome": "bad"}
}
```

The rich fields (owner, amount at stake, market context) exist because recall quality depends on the detail:
a one-line decision retrieves on keyword overlap, whereas an owner, an amount and the situation of the moment
retrieve on situation and give a judge something checkable. Mirror records carry an explicit note that a
near-identical decision went badly and that the single difference is described in the decision line, so the
difference step has something to find without guessing.

## Live bank

| | Value |
|---|---|
| Documents | 77 |
| Observations | 68 |
| Nodes | 276 |
| Links | 6802 |
| Pending | 0 |
| Directives | 5 |

72 of the 77 documents are the corpus. The other 5 are the ledger seed (below).

## Calibration ledger

| | Value |
|---|---|
| Flags raised | 5 |
| Ignored anyway | 4 |
| Cost something | 3 |

Promoted classes: `pricing@discount`, `hiring@senior-hire`, `marketing@budget-shift`. Promotion is derived,
not hand-listed: every warning row that is `costed` contributes its `domain@decision_type`, and the ranker
boosts that class. Five warnings is one warning per decision id, deduped on read (Hindsight extracts several
facts per flag document, so 5 flags came back as 20 facts before dedupe).

## Prompts (the demo path)

| Key | Label | Expected domain / type |
|---|---|---|
| `A` | discount to close a renewal | pricing / discount |
| `B` | senior hire with no written scope | hiring / senior-hire |
| `C` | decision with no precedent | expansion / new-office |
| `D` | close an audit finding with a stopgap | compliance / audit-finding |
| `E` | exclusive reseller deal | partnership / reseller-agreement |

Measured production output:

| Preset | Classification | Mode | Result |
|---|---|---|---|
| A pricing/discount | `pricing / renewal-discount` | decision | high 0.79, cites D-2025-0002, D-2025-0013 (bad), D-2025-0023 (mirror, fine) |
| B hiring/senior-hire | `hiring / senior-hire` | decision | high |
| C expansion/new-office | `expansion / new-office` | decision | **no precedent**, refuses, emits a labelled LOW-confidence guess with 3 watch items |
| D compliance/audit-finding | `compliance / audit-finding` | decision | high 0.67, cites D-2026-0038 (bad) + D-2027-0062 (mirror) |
| E partnership/exclusivity | `partnership / exclusivity-agreement` | decision | high 0.67, cites D-2026-0045 (bad) + D-2027-0068 (mirror) |

The no-precedent path: the refusal is the answer, and a clearly-fenced guess follows it, labelled "If I had to
guess", badged low confidence, captioned as general practice with no precedent cited. The guess prompt forbids
citing an id and `_guess_block()` strips any id it finds, so a guess can never launder itself into a citation.
Rendered full width.

Preset C is the one that matters most for the anti-black-box story. Rehearse it twice.

## Ground truth

`POST /api/biz/seed` writes `data/biz_ground_truth.json`, computed from the plan table, **not** from the LLM:

```python
{
  "decisions": [
    {"decision_id": "D-2025-0000", "idx": 0, "date": "2025-02-03", "domain": "pricing",
     "decision_type": "price-increase", "pattern_id": null, "outcome": "good",
     "materialised": false, "is_mirror": false,
     "precedent_derivable": false, "precedent_decision_id": null}
  ],
  "totals": {"decisions": 72, "materialised": 25, "materialised_with_prior": 15,
             "derivable_coverage": 0.6}
}
```

Two coverage numbers get reported, and the difference between them is the honest bit:

```
derivable coverage  = materialised_with_prior / materialised            # corpus ceiling, 60%
found coverage      = materialised where the agent actually cited one   # agent performance
```

If the agent only finds some of the derivable ones, say so on screen. Hiding that gap is the fastest way to
lose a technical judge.

# Part 2 — Deploy corpus (legacy, still served)

## Generator parameters

```python
START      = datetime(2025, 7, 20, 9, 30)
STEP_DAYS  = 11                      # one launch every 11 days -> 40 launches = 2025-07-20 .. 2026-09-22
SERVICES   = ["payments-service", "auth-service", "search-index",
              "ingest-pipeline", "notification-worker", "billing-api"]
CLASSES    = ["config-only", "dependency-bump", "schema-migration",
              "flag-flip", "infra-change"]
```

Weight classes so config-only and dependency-bump dominate, which is realistic for pre-mortem purposes:
`config-only` (13), `dependency-bump` (7), `flag-flip` (9), `schema-migration` (8), `infra-change` (3).

Date of launch `i` = `START + timedelta(days=11*i)`, `i` from 0 to 39. The replay buckets the launches that
materialised into chunks of 5, which currently yields 3 epochs (5, 5, 2).

## Failure patterns (the interlocks)

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

12 of the 40 launches materialise: 9 `incident`, 3 `degraded`, 28 `clean`. Incidence is deliberately around
30%: high enough that the flags are not rare, low enough that precision is a real question.

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

## Ground truth

`POST /api/seed` writes `data/ground_truth.json`, computed from the table, **not** from the LLM:

```python
{
  "launches": [
    {"launch_id": "...", "date": "...", "service": "...", "change_class": "...",
     "pattern_id": "P1", "materialised": true,
     "precedent_derivable": true,     # a prior launch in the same pattern_id exists
     "precedent_launch_id": "..."}    # that prior launch, or null
  ],
  "totals": {"launches": 40, "materialised": 12, "materialised_with_prior": 7,
             "derivable_coverage": 0.583}
}
```

The replay reports `{launches, found_precedent, found_coverage, derivable, derivable_coverage, gap}`. Current
values: 12 launches considered, 7 with a precedent found, coverage 0.583 both ways, gap 0. The method line is
explicit that `recall(query_timestamp=...)` is a ranking hint and does not filter on Hindsight API 0.10.1, so
no-lookahead is enforced in code.

## Ignored-warning ledger seed

Flags recorded during the replay, so the ledger has a history:

| Launch idx | Flag raised | Ignored? | Cost |
|---|---|---|---|
| idx 4 (P1 payments) | config-only pool change on payments | yes | incident |
| 9 (P4 ingest) | batch size raised without profiling | yes | incident |
| 16 (P1 payments) | config-only pool change on payments | no | — (actioned, no incident) |
| 13 (P3 search) | schema migration without pre-backfill | yes | no incident that time |

Result: 4 flags, 3 ignored, 2 of the ignored ones cost an incident, and the promoted class is
`config-only` on `payments-service`. Promoting that class changes `rank()` on the demo query — the same
question returns a different top result once the ledger has history. That is the learning beat.

## Target metric bands and the tuning knobs

Design targets for the deploy replay, not promises. After the first full `replay()`, **freeze the actual
numbers**; if they fall outside the band, tune the knob, do not tune the write-up.

| Metric | Target | Knob |
|---|---|---|
| Flag precision, early epochs -> late | 64% -> 88% | `MIN_PROOF` in `rank()`, pattern specificity in the queries |
| Coverage, early epochs -> late | 31% -> 79% | corpus density per pattern (add instances to later epochs), `budget` in recall |
| `no_precedent` rate | high early, near zero late | `MIN_PROOF`; too high and it refuses everything, too low and it stretches |
| Flag recall on the ledger classes | 100% after promotion | `prefer=` weight in `rank()` |

## Demo presets (three pending deploy changes)

Kept for the legacy path. The product's demo path is the five business prompts in Part 1.

| Preset | Pending change | Expected behaviour |
|---|---|---|
| **A — P1 match** | payments-service, config-only, reduce `pool-size` 40 -> 20, nothing else touched | 3 precedents including `L-2026-0412`, risk **high**, flip detail = "`max_overflow` was also raised last time; you have not raised it", cited fix = P1 fix |
| **B — P3 match** | search-index, schema-migration on a indexed column, backfill not scheduled | precedents cite the pre-backfill failures, risk **medium-high**, flip detail = "the clean case ran the backfill first; yours has none scheduled" |
| **C — no precedent** | infra-change, `notification-worker` region move, no parameter change | `no_precedent`; coverage stated; two nearest-but-insufficient precedents shown; risk **unknown** |

Preset A also demonstrates the ledger: with the ledger populated, the payments config-only class is
promoted, so A's card appears first and carries the "you were warned about this class twice" line.

## Contradiction case (show it, do not hide it)

`L-2025-XXXX` (idx 25) is a clean mirror of P1: same pool change, but `max_overflow` raised together.
Show both records side by side on the P1 card. Risk stays `medium`, the card states why it is not `high`,
and the agent never averages the two into a comforting middle. Judges remember the case where the agent
argued both sides.
