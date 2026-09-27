"""The 40-launch corpus. Single source of truth for seed, ground truth, replay and the demo presets.

Design rules (docs/DATA.md):
 - 6 interlocked failure patterns, each with at least one CLEAN MIRROR: a near-identical launch that did
   not break, differing in exactly one parameter. The mirror is what makes flip-detail extraction real
   and what a similarity search gets wrong.
 - `timestamp` is the launch date, so `occurred_start` per extracted fact is date-aware.
 - No real employer, customer or incident data. Every name and number here is invented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

START = datetime(2025, 7, 20, 9, 30)
STEP_DAYS = 11


@dataclass(frozen=True)
class Launch:
    idx: int
    launch_id: str
    service: str
    change_class: str
    pattern_id: str | None
    outcome: str  # clean | degraded | incident
    change: str
    diff: str
    symptom: str
    fix: str
    is_mirror: bool = False
    mirror_of: int | None = None

    @property
    def date(self) -> datetime:
        return START + timedelta(days=STEP_DAYS * self.idx)

    @property
    def materialised(self) -> bool:
        return self.outcome in ("degraded", "incident")

    def text(self) -> str:
        parts = [
            f"Launch {self.launch_id} | {self.service} | {self.change_class}",
            f"Change: {self.change}",
            f"Diff: {self.diff}",
        ]
        if self.symptom:
            parts.append(f"Symptom: {self.symptom}")
        parts.append(f"Outcome: {self.outcome}" + (f". Fix applied: {self.fix}" if self.fix else "."))
        if self.is_mirror:
            parts.append(
                "Note: this is a near-identical change to an earlier launch that DID cause an incident. "
                "The single difference that avoided the incident is described in the change line."
            )
        return "\n".join(parts)

    def metadata(self) -> dict[str, str]:
        m = {
            "launch_id": self.launch_id,
            "service": self.service,
            "change_class": self.change_class,
            "outcome": self.outcome,
        }
        if self.pattern_id:
            m["pattern_id"] = self.pattern_id
        if self.is_mirror:
            m["is_mirror"] = "true"
        return m


FIXES = {
    "P1": "raised max_overflow to 20 and set pool_pre_ping=true; the pool had no headroom for the p99 burst path",
    "P2": "pinned the JWT library to the previous minor, then adopted the new default only alongside the HS256 migration",
    "P3": "ran the backfill job to completion before the migration and throttled replica reads during it",
    "P4": "reverted the batch size, added the memory profiler to CI, capped at the profiled ceiling",
    "P5": "shipped the provider idempotency key first, then re-enabled the retry flag",
    "P6": "pinned the rounding mode explicitly in the migration and added a decimal-delta assertion test",
}

SYMPTOMS = {
    "P1": (
        "p99 latency 210ms -> 1.9s. HikariPool-1 - Connection is not available, request timed out "
        "after 30000ms (total=20, active=20, idle=0, waiting=83)"
    ),
    "P2": "401 rate 0.02% -> 4.1%. jwt.exceptions.InvalidSignatureError: Signature verification failed",
    "P3": "replica lag 0.4s -> 47s; stale_doc_ratio 0.7% -> 12.4%",
    "P4": "OOMKilled (container ingest-worker, peak_rss 1.8Gi / limit 1.5Gi); consumer lag 1.2k -> 340k messages",
    "P5": "duplicate_send_rate 0.1% -> 6.3%; provider 429 bursts, no idempotency key on the retry path",
    "P6": "avg invoice_total_delta +0.43%; rounding mode changed half-up -> half-even in the decimal migration",
}

# (idx, pattern, service, class, kind)  kind: brk | mir | plain
PLAN: list[tuple[int, str | None, str, str, str]] = [
    (0, None, "payment-router", "dependency-bump", "plain"),
    (1, None, "search-index", "flag-flip", "plain"),
    (2, "P3", "search-index", "schema-migration", "brk"),
    (3, None, "auth-service", "config-only", "plain"),
    (4, "P1", "payments-service", "config-only", "brk"),
    (5, None, "ingest-pipeline", "flag-flip", "plain"),
    (6, "P6", "billing-api", "schema-migration", "mir"),
    (7, "P2", "auth-service", "dependency-bump", "brk"),
    (8, None, "ingest-pipeline", "infra-change", "plain"),
    (9, "P4", "ingest-pipeline", "config-only", "brk"),
    (10, None, "payments-service", "schema-migration", "plain"),
    (11, "P5", "notification-worker", "flag-flip", "brk"),
    (12, None, "search-index", "dependency-bump", "plain"),
    (13, "P3", "search-index", "schema-migration", "brk"),
    (14, None, "billing-api", "config-only", "plain"),
    (15, None, "auth-service", "flag-flip", "plain"),
    (16, "P1", "payments-service", "config-only", "brk"),
    (17, None, "ingest-pipeline", "infra-change", "plain"),
    (18, "P4", "ingest-pipeline", "config-only", "mir"),
    (19, "P6", "billing-api", "schema-migration", "brk"),
    (20, None, "search-index", "config-only", "plain"),
    (21, "P2", "auth-service", "dependency-bump", "brk"),
    (22, "P5", "notification-worker", "flag-flip", "mir"),
    (23, None, "payments-service", "flag-flip", "plain"),
    (24, "P4", "ingest-pipeline", "config-only", "brk"),
    (25, "P1", "payments-service", "config-only", "mir"),
    (26, None, "billing-api", "dependency-bump", "plain"),
    (27, "P3", "search-index", "schema-migration", "brk"),
    (28, None, "auth-service", "infra-change", "plain"),
    (29, "P5", "notification-worker", "flag-flip", "brk"),
    (30, None, "search-index", "flag-flip", "plain"),
    (31, "P1", "payments-service", "config-only", "brk"),
    (32, None, "ingest-pipeline", "dependency-bump", "plain"),
    (33, None, "billing-api", "config-only", "plain"),
    (34, "P2", "auth-service", "dependency-bump", "mir"),
    (35, None, "payments-service", "schema-migration", "plain"),
    (36, None, "notification-worker", "config-only", "plain"),
    (37, "P3", "search-index", "schema-migration", "mir"),
    (38, None, "ingest-pipeline", "flag-flip", "plain"),
    (39, None, "search-index", "config-only", "plain"),
]

# Per-pattern change/diff text. `brk` is the breaking form, `mir` the clean near-twin.
CHANGE: dict[str, dict[str, tuple[str, str]]] = {
    "P1": {
        "brk": ("reduced connection pool size 40 -> 20, no other parameter touched",
                "application.yml: hikari.pool-size 40 -> 20"),
        "mir": ("reduced connection pool size 40 -> 20 AND raised hikari.max-overflow 10 -> 20 in the same commit",
                "application.yml: hikari.pool-size 40 -> 20; hikari.max-overflow 10 -> 20"),
    },
    "P2": {
        "brk": ("bumped the JWT library minor version (3.2.1 -> 3.3.0), defaults inherited",
                "requirements.txt: pyjwt 3.2.1 -> 3.3.0"),
        "mir": ("bumped the JWT library minor version but pinned it exactly and set the signature algorithm explicitly",
                "requirements.txt: pyjwt==3.3.0; auth config algorithm: HS256"),
    },
    "P3": {
        "brk": ("schema migration on an indexed column, backfill NOT scheduled before it",
                "migrations/0042_add_search_tsv_index.sql (no preceding backfill step)"),
        "mir": ("schema migration on an indexed column, with the backfill job run to completion first and replica reads throttled",
                "migrations/0051_add_doc_rank_index.sql + backfill job 0051 completed before apply"),
    },
    "P4": {
        "brk": ("raised the ingest batch size 500 -> 2000 without a memory profile",
                "ingest-pipeline config: batch_size 500 -> 2000"),
        "mir": ("reduced the ingest batch size deliberately after profiling, ceiling derived from measured peak RSS",
                "ingest-pipeline config: batch_size 2000 -> 800, profiled peak_rss ceiling 1.4Gi"),
    },
    "P5": {
        "brk": ("doubled the notification retry flag, provider-side idempotency key not yet shipped",
                "flags: notification.retry.max_attempts 2 -> 4"),
        "mir": ("raised the notification retry flag only after the provider idempotency key was live in production",
                "flags: notification.retry.max_attempts 2 -> 4 (idempotency_key=enabled already deployed)"),
    },
    "P6": {
        "brk": ("decimal column migration on the invoice total path, rounding mode left to the database default",
                "migrations/0038_invoice_total_decimal.sql (rounding mode unset)"),
        "mir": ("decimal column migration on an unrelated column, no rounding path involved",
                "migrations/0029_customer_credit_decimal.sql (no Money rounding path)"),
    },
}

PLAIN_CHANGES = {
    "dependency-bump": ("routine dependency bump, minor version, lockfile regenerated",
                        "requirements.txt: two minor bumps"),
    "flag-flip": ("feature flag toggled for 10% of traffic, no retry or timeout path touched",
                  "flags: checkout.new_summary = 0.1"),
    "schema-migration": ("additive schema migration, new nullable column, no index and no backfill",
                         "migrations/00XX_add_nullable_meta_column.sql"),
    "config-only": ("log level raised and a timeout lowered within tested bounds",
                    "config: log.level INFO -> DEBUG"),
    "infra-change": ("node pool image refreshed to the latest patch, no application config touched",
                     "infra: nodepool image patch release"),
}

PLAIN_SYMPTOM = {
    "flag-flip": "no measurable change in error rate or latency",
    "schema-migration": "no measurable change; migration applied in 4s",
    "config-only": "no measurable change",
    "dependency-bump": "no measurable change",
    "infra-change": "no measurable change",
}


# A pattern break MUST materialise, or the pattern is noise. Variation is deliberate:
# most breaks are incidents, some are milder degradations, and exactly two breaks stay clean
# (the "we got lucky" case) so flag precision is a real question rather than a guaranteed 100%.
_BREAK_PLAN: dict[str, list[str]] = {
    # in order of appearance across the corpus
    "P1": ["incident", "incident", "clean"],            # idx 4, 16, 31
    "P2": ["incident", "incident"],                     # idx 7, 21
    "P3": ["incident", "degraded", "incident"],         # idx 2, 13, 27
    "P4": ["incident", "degraded"],                     # idx 9, 24
    "P5": ["incident", "incident"],                     # idx 11, 29
    "P6": ["degraded"],                                 # idx 19
}


def corpus() -> list[Launch]:
    out: list[Launch] = []
    seen_breaks: dict[str, int] = {}
    for idx, pattern, service, change_class, kind in PLAN:
        launch_id = f"L-{START.year + (START + timedelta(days=STEP_DAYS * idx)).year - START.year}"  # placeholder
        d = START + timedelta(days=STEP_DAYS * idx)
        launch_id = f"L-{d.year}-{idx:04d}"
        if kind == "plain" or pattern is None:
            change, diff = PLAIN_CHANGES[change_class]
            # plain launches are clean on purpose: every materialised outcome should trace to a pattern,
            # otherwise the corpus has noise patterns the agent cannot learn and its precision looks random.
            out.append(Launch(idx, launch_id, service, change_class, None, "clean", change, diff,
                              PLAIN_SYMPTOM.get(change_class, "no measurable change"), ""))
            continue
        key = "mir" if kind == "mir" else "brk"
        change, diff = CHANGE[pattern][key]
        if kind == "mir":
            out.append(Launch(idx, launch_id, service, change_class, pattern, "clean", change, diff,
                              "no incident. The near-identical earlier change to this service did cause one.",
                              "", is_mirror=True))
        else:
            seq = _BREAK_PLAN[pattern]
            n = seen_breaks.get(pattern, 0)
            outcome = seq[n] if n < len(seq) else seq[-1]
            seen_breaks[pattern] = n + 1
            symptom = SYMPTOMS[pattern] if outcome != "clean" else (
                "no incident. This break of the pattern did not materialise this time.")
            out.append(Launch(idx, launch_id, service, change_class, pattern, outcome, change, diff,
                              symptom, FIXES[pattern] if outcome != "clean" else ""))
    return out


# ---------------------------------------------------------------- demo presets
@dataclass(frozen=True)
class Pending:
    key: str
    label: str
    service: str
    change_class: str
    change: str
    diff: str
    expect: str
    pattern_hint: str | None = None

    @property
    def materialised(self) -> bool:
        return False


PRESETS: list[Pending] = [
    Pending(
        key="A",
        label="config-only pool change on payments-service",
        service="payments-service",
        change_class="config-only",
        change="reduce connection pool size 40 -> 20, no other parameter touched",
        diff="application.yml: hikari.pool-size 40 -> 20",
        expect="precedent cited, risk high, flip detail names max_overflow",
        pattern_hint="P1",
    ),
    Pending(
        key="B",
        label="schema migration on search-index without a scheduled backfill",
        service="search-index",
        change_class="schema-migration",
        change="add an index to a large text column and migrate, backfill not scheduled",
        diff="migrations/0061_add_doc_search_index.sql (no backfill step)",
        expect="precedents cite the pre-backfill failures, risk medium-high",
        pattern_hint="P3",
    ),
    Pending(
        key="C",
        label="infra-change: node pool region move on notification-worker",
        service="notification-worker",
        change_class="infra-change",
        change="move the node pool to a different region, no application parameter changes",
        diff="infra: nodepool zone eu-west-1a -> eu-west-1c",
        expect="no_precedent, risk unknown, coverage stated, two declined precedents",
        pattern_hint=None,
    ),
]

PRESET_BY_KEY = {p.key: p for p in PRESETS}


# ---------------------------------------------------------------- ledger seed
# (idx of launch the flag was raised on, flag text, ignored?, did it cost an incident?)
LEDGER_SEED = [
    (4, "config-only pool change on payments-service", True, True),
    (9, "batch size raised on ingest-pipeline without a memory profile", True, True),
    (16, "config-only pool change on payments-service", False, False),
    (13, "schema migration on search-index without a pre-backfill", True, False),
]


def ground_truth() -> dict:
    """Computed from this table, never from an LLM. Drives the reproducibility claim."""
    launches = corpus()
    seen: dict[str, str] = {}
    rows = []
    materialised_with_prior = 0
    for l in launches:
        prior = seen.get(l.pattern_id) if l.pattern_id else None
        if l.materialised:
            if prior:
                materialised_with_prior += 1
        if l.pattern_id and not l.is_mirror and l.materialised:
            seen.setdefault(l.pattern_id, l.launch_id)
        elif l.pattern_id and l.pattern_id not in seen:
            # a clean mirror still establishes that the pattern occurs before this launch
            seen[l.pattern_id] = l.launch_id
        rows.append({
            "launch_id": l.launch_id,
            "idx": l.idx,
            "date": l.date.date().isoformat(),
            "service": l.service,
            "change_class": l.change_class,
            "pattern_id": l.pattern_id,
            "outcome": l.outcome,
            "materialised": l.materialised,
            "is_mirror": l.is_mirror,
            "precedent_derivable": prior is not None,
            "precedent_launch_id": prior,
        })
    materialised = sum(1 for l in launches if l.materialised)
    return {
        "launches": rows,
        "totals": {
            "launches": len(launches),
            "materialised": materialised,
            "materialised_with_prior": materialised_with_prior,
            "derivable_coverage": (materialised_with_prior / materialised) if materialised else 0.0,
        },
    }
