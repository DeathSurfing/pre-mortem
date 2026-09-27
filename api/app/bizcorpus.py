"""Business decision corpus. Same shape as the deploy corpus, different domain.

Why interlocked patterns matter here too: a bag of unrelated business anecdotes gives every precedent
proof 1 and no trend, which destroys the whole credibility story. So this is 6 recurring decision
domains, each with several instances and at least one CLEAN MIRROR: a near-identical decision that went
fine because of exactly one differing detail. The mirror is what the flip-detail step is extracted from.

Every name, number and outcome here is invented. No real company data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

START = datetime(2025, 2, 3)
STEP_DAYS = 14


@dataclass(frozen=True)
class Decision:
    idx: int
    decision_id: str
    domain: str  # pricing | hiring | vendor | marketing | launch | buildvsbuy
    decision_type: str
    pattern_id: str | None
    outcome: str  # good | mixed | bad
    decision: str
    rationale: str
    result: str
    lesson: str
    is_mirror: bool = False
    # richer scenario detail; empty for decisions that only need the base shape
    owner: str = ""
    scale: str = ""
    context: str = ""

    @property
    def date(self) -> datetime:
        return START + timedelta(days=STEP_DAYS * self.idx)

    @property
    def materialised(self) -> bool:
        return self.outcome in ("mixed", "bad")

    def text(self) -> str:
        # The rich fields are here because recall quality depends on the detail: a one-line decision
        # retrieves on keyword overlap, whereas an owner, an amount, and the market context of the moment
        # retrieve on situation and give a judge something checkable.
        parts = [
            f"Business decision {self.decision_id} | {self.domain} | {self.decision_type}",
            f"Decided on: {self.date.date().isoformat()}",
        ]
        if self.owner:
            parts.append(f"Owner: {self.owner}")
        if self.scale:
            parts.append(f"Amount at stake: {self.scale}")
        if self.context:
            parts.append(f"Context at the time: {self.context}")
        parts += [
            f"Decision: {self.decision}",
            f"Rationale at the time: {self.rationale}",
            f"Result: {self.result}",
        ]
        if self.lesson:
            parts.append(f"Lesson recorded: {self.lesson}")
        if self.is_mirror:
            parts.append(
                "Note: this is a near-identical decision to an earlier one that went badly. "
                "The single difference that made it work is described in the decision line."
            )
        return "\n".join(parts)

    def metadata(self) -> dict[str, str]:
        m = {
            "decision_id": self.decision_id,
            "domain": self.domain,
            "decision_type": self.decision_type,
            "outcome": self.outcome,
        }
        if self.pattern_id:
            m["pattern_id"] = self.pattern_id
        if self.is_mirror:
            m["is_mirror"] = "true"
        if self.owner:
            m["owner"] = self.owner
        return m


# ---------------------------------------------------------------- pattern definitions

RESULTS = {
    "B1": "Gross margin fell 6.2 points over two quarters. Three other accounts cited the same discount "
          "in their next renewal, so the discounted price became the de facto list price. Finance had "
          "flagged the margin impact at approval and it was overridden.",
    "B2": "The hire ramped slowly, delivered no scoped outcome in the first two quarters, and left at "
          "month 11. Recruiting cost plus salary was roughly 1.4x budget with no attributable result. "
          "The role was never written down beyond a title.",
    "B3": "Migration took 5 months against a 6 week estimate. Two integrations were undocumented and had "
          "to be rebuilt. The annual saving was 22 percent of what the business case claimed, and the "
          "team spent a quarter on the move instead of roadmap work.",
    "B4": "CAC in that channel rose 68 percent within a quarter as spend scaled, and incrementality "
          "testing later showed roughly 40 percent of the attributed conversions would have happened "
          "anyway. Budget had already been reallocated away from two working channels.",
    "B5": "Launch went out to all customers at once. Support queue tripled, refund rate went from 1.1 "
          "percent to 4.8 percent, and the first two weeks of feedback were dominated by an onboarding "
          "bug rather than the feature itself.",
    "B6": "Build cost came in close to estimate but maintenance did not. Two engineers were effectively "
          "dedicated to it within a year, and the team could not staff the roadmap item it was meant to "
          "unblock. The buy option was never re-priced after year one.",
}

LESSONS = {
    "B1": "tie any discount to a term commitment or a volume floor, and log the margin delta at approval",
    "B2": "write a 90 day mandate with named deliverables before opening the role",
    "B3": "run the new vendor in parallel for one billing cycle and document every integration before cutting over",
    "B4": "hold a small untargeted control group before scaling spend in any single channel",
    "B5": "stage the rollout to a cohort with support staffing in place before general availability",
    "B6": "price the maintenance burden over three years, not just the build, and write the exit plan",
}

CHANGES: dict[str, dict[str, tuple[str, str]]] = {
    "B1": {
        "brk": ("give Acme a 30 percent discount on the renewal to close it this quarter, no term change",
                "protect the quarter, competitor was cheaper, champion asked for a gesture"),
        "mir": ("give Acme a 30 percent discount on the renewal, in exchange for a 3 year term commitment "
                "and a 250 seat volume floor",
                "protect the quarter, competitor was cheaper, champion asked for a gesture"),
    },
    "B2": {
        "brk": ("hire a senior platform engineer at the top of band, scope to be defined once they start",
                "the team is stretched and the roadmap needs senior capacity"),
        "mir": ("hire a senior platform engineer at the top of band against a written 90 day mandate with "
                "named deliverables and a review gate",
                "the team is stretched and the roadmap needs senior capacity"),
    },
    "B3": {
        "brk": ("switch our CRM vendor to the cheaper option on price alone, cut over at contract end",
                "28 percent cheaper on list price, incumbent raised prices at renewal"),
        "mir": ("switch our CRM vendor to the cheaper option, with a parallel run for one billing cycle and "
                "every integration documented before cut over",
                "28 percent cheaper on list price, incumbent raised prices at renewal"),
    },
    "B4": {
        "brk": ("move 60 percent of paid budget into the channel that showed the best last click ROAS",
                "last click ROAS was 3.1 against 1.4 on the other channels"),
        "mir": ("increase spend in the best performing channel, holding a small untargeted control group to "
                "measure incrementality before scaling",
                "last click ROAS was 3.1 against 1.4 on the other channels"),
    },
    "B5": {
        "brk": ("launch the new billing portal to all customers on the same day",
                "the feature was complete and the quarter needed the revenue recognition"),
        "mir": ("launch the new billing portal to a 5 percent cohort first, with support staffing in place "
                "before general availability",
                "the feature was complete and the quarter needed the revenue recognition"),
    },
    "B6": {
        "brk": ("build the internal scheduling service in house because the build quote was cheaper than "
                "three years of licence",
                "the build quote was 40 percent cheaper than the licence over the same period"),
        "mir": ("build the internal scheduling service in house, with the maintenance burden priced over "
                "three years and a written exit plan",
                "the build quote was 40 percent cheaper than the licence over the same period"),
    },
}

# (idx, pattern, domain, type, kind)
PLAN: list[tuple[int, str | None, str, str, str]] = [
    (0, None, "pricing", "price-increase", "plain"),
    (1, None, "hiring", "backfill", "plain"),
    (2, "B1", "pricing", "discount", "brk"),
    (3, None, "marketing", "channel-test", "plain"),
    (4, None, "vendor", "renewal", "plain"),
    (5, "B3", "vendor", "vendor-switch", "brk"),
    (6, None, "launch", "feature-ga", "plain"),
    (7, "B2", "hiring", "senior-hire", "brk"),
    (8, None, "buildvsbuy", "buy", "plain"),
    (9, "B4", "marketing", "budget-shift", "brk"),
    (10, None, "pricing", "packaging", "plain"),
    (11, "B5", "launch", "feature-ga", "brk"),
    (12, None, "hiring", "contractor-conversion", "plain"),
    (13, "B1", "pricing", "discount", "brk"),
    (14, None, "vendor", "renewal", "plain"),
    (15, None, "marketing", "channel-test", "plain"),
    (16, "B6", "buildvsbuy", "build", "brk"),
    (17, None, "launch", "feature-ga", "plain"),
    (18, "B2", "hiring", "senior-hire", "mir"),
    (19, None, "pricing", "price-increase", "plain"),
    (20, "B3", "vendor", "vendor-switch", "brk"),
    (21, "B4", "marketing", "budget-shift", "mir"),
    (22, None, "buildvsbuy", "buy", "plain"),
    (23, "B1", "pricing", "discount", "mir"),
    (24, None, "hiring", "backfill", "plain"),
    (25, "B5", "launch", "feature-ga", "mir"),
    (26, None, "marketing", "channel-test", "plain"),
    (27, "B2", "hiring", "senior-hire", "brk"),
    (28, None, "vendor", "renewal", "plain"),
    (29, "B6", "buildvsbuy", "build", "mir"),
    (30, None, "pricing", "packaging", "plain"),
    (31, "B3", "vendor", "vendor-switch", "brk"),
    (32, None, "launch", "feature-ga", "plain"),
    (33, "B4", "marketing", "budget-shift", "brk"),
    (34, None, "hiring", "contractor-conversion", "plain"),
    (35, "B5", "launch", "feature-ga", "brk"),
]

# a break must materially break, or the pattern is noise the agent cannot learn
_BREAK_PLAN: dict[str, list[str]] = {
    "B1": ["bad", "bad", "good"],       # idx 2, 13, 23(mirror handled separately)
    "B2": ["bad", "bad"],               # idx 7, 27
    "B3": ["bad", "mixed", "bad"],      # idx 5, 20, 31
    "B4": ["bad", "bad"],               # idx 9, 33
    "B5": ["bad", "mixed"],             # idx 11, 35
    "B6": ["bad"],                      # idx 16
}

PLAIN = {
    "pricing": ("raise list price 4 percent across all tiers at the new year",
                "input costs rose and the last increase was two years ago",
                "No measurable churn change. Net revenue up 3.1 percent.", ""),
    "hiring": ("backfill a departing mid level engineer on the existing band",
               "team capacity gap, scope well understood from the departing person's work",
               "Backfill hired in 6 weeks and productive by month 2.", ""),
    "vendor": ("renew the incumbent monitoring vendor at the negotiated uplift",
               "tooling is embedded, renewal uplift was within budget",
               "Renewed without incident. No migration cost.", ""),
    "marketing": ("run a 3 week test in a second channel at 5 percent of budget",
                  "the channel is unproven and the test is cheap",
                  "Inconclusive but cheap. No budget reallocation made.", ""),
    "launch": ("release a minor feature update to the existing beta cohort",
               "low blast radius, cohort already opted in",
               "Shipped cleanly. No support impact.", ""),
    "buildvsbuy": ("buy a standard analytics tooling licence on an annual term",
                   "the requirement is generic and the annual term keeps optionality",
                   "Adopted without incident. Renewal decision deferred a year.", ""),
}


def _rich(domain: str, dtype: str) -> dict[str, str]:
    """Owner / scale / context for a domain+type, empty when the base corpus is enough."""
    from .bizcorpus_extra import RICH
    return RICH.get((domain, dtype), {}) if ENRICH else {}


def _merge_extras(extras, key):
    """Overlay the richer half's tables on top of the base ones, so both halves resolve."""
    merged = dict(globals().get(key) or {})
    merged.update(extras)
    return merged


def corpus() -> list[Decision]:
    out: list[Decision] = []
    seen_breaks: dict[str, int] = {}
    for idx, pattern, domain, dtype, kind in FULL_PLAN:
        d = START + timedelta(days=STEP_DAYS * idx)
        did = f"D-{d.year}-{idx:04d}"
        if kind == "plain" or pattern is None:
            dec, rat, res, lesson = FULL_PLAIN[domain]
            r = _rich(domain, dtype)
            out.append(Decision(idx, did, domain, dtype, None, "good", dec, rat, res, lesson,
                                owner=r.get("owner", ""), scale=r.get("scale", ""),
                                context=r.get("context", "")))
            continue
        key = "mir" if kind == "mir" else "brk"
        dec, rat = FULL_CHANGES[pattern][key]
        r = _rich(domain, dtype)
        if kind == "mir":
            out.append(Decision(idx, did, domain, dtype, pattern, "good", dec, rat,
                                "Went as intended. The near-identical earlier decision in this domain did not.",
                                FULL_LESSONS[pattern], is_mirror=True,
                                owner=r.get("owner", ""), scale=r.get("scale", ""),
                                context=r.get("context", "")))
        else:
            seq = FULL_BREAK_PLAN[pattern]
            n = seen_breaks.get(pattern, 0)
            outcome = seq[n] if n < len(seq) else seq[-1]
            seen_breaks[pattern] = n + 1
            res = FULL_RESULTS[pattern] if outcome != "good" else (
                "No material harm this time, though the same decision shape has gone badly before.")
            out.append(Decision(idx, did, domain, dtype, pattern, outcome, dec, rat, res,
                                FULL_LESSONS[pattern] if outcome != "good" else "",
                                owner=r.get("owner", ""), scale=r.get("scale", ""),
                                context=r.get("context", "")))
    return out


# ---------------------------------------------------------------- merged base + extra history

# ENRICH toggles the richer half (bizcorpus_extra): owners, amounts at stake, market context, and four
# additional decision areas. Off, this module behaves exactly as the original 36-decision corpus.
ENRICH = True

if ENRICH:
    from . import bizcorpus_extra as _extra

    FULL_PLAN = PLAN + _extra.EXTRA_PLAN
    FULL_BREAK_PLAN = {**_BREAK_PLAN, **_extra.EXTRA_BREAK_PLAN}
    FULL_RESULTS = {**RESULTS, **_extra.EXTRA_RESULTS}
    FULL_LESSONS = {**LESSONS, **_extra.EXTRA_LESSONS}
    FULL_CHANGES = {**CHANGES, **_extra.EXTRA_CHANGES}
    FULL_PLAIN = {**PLAIN, **_extra.EXTRA_PLAIN}
else:
    FULL_PLAN = PLAN
    FULL_BREAK_PLAN = _BREAK_PLAN
    FULL_RESULTS = RESULTS
    FULL_LESSONS = LESSONS
    FULL_CHANGES = CHANGES
    FULL_PLAIN = PLAIN


# ---------------------------------------------------------------- demo prompts (free text)

@dataclass(frozen=True)
class Prompt:
    key: str
    label: str
    text: str
    expect_domain: str
    expect_type: str
    expect: str


PROMPTS: list[Prompt] = [
    Prompt(
        key="A",
        label="discount to close a renewal",
        text="Acme's renewal is at risk and their champion is asking for a gesture because a competitor "
             "came in cheaper. I want to give them a 30 percent discount to close it this quarter. "
             "Should I?",
        expect_domain="pricing",
        expect_type="discount",
        expect="precedent cited, margin risk flagged, flip detail names the term commitment",
    ),
    Prompt(
        key="B",
        label="senior hire with no written scope",
        text="Our platform team is stretched and the roadmap needs senior capacity. I want to hire a "
             "senior platform engineer at the top of the band and define the scope once they start. "
             "What has gone wrong before when we did this?",
        expect_domain="hiring",
        expect_type="senior-hire",
        expect="precedents cite the ramp failures, flip detail names the 90 day mandate",
    ),
    Prompt(
        key="C",
        label="decision with no precedent",
        text="We are considering opening an office in Lisbon to get closer to European customers. "
             "Is that a good idea for us?",
        expect_domain="expansion",
        expect_type="new-office",
        expect="no precedent, no confident answer, neighbouring decisions shown and declined",
    ),
]

PROMPTS = PROMPTS + [Prompt(**p) for p in _extra.EXTRA_PROMPTS] if ENRICH else PROMPTS

PROMPT_BY_KEY = {p.key: p for p in PROMPTS}


# ---------------------------------------------------------------- ledger

# (idx of the decision the warning was raised on, warning text, ignored?, did it cost anything?)
LEDGER_SEED = [
    (2, "30 percent discount with no term commitment erodes margin and sets a pricing precedent", True, True),
    (7, "senior hire without a written mandate has failed to ramp twice before", True, True),
    (9, "concentrating paid budget on last click ROAS ignores incrementality", True, True),
    (13, "same discount shape as an earlier decision that damaged gross margin", False, False),
    (5, "vendor switch on price alone has hidden integration cost", True, False),
]


def ground_truth() -> dict:
    """Computed from this table, never from an LLM. Drives the reproducibility claim."""
    decisions = corpus()
    seen: dict[str, str] = {}
    rows = []
    materialised_with_prior = 0
    for d in decisions:
        prior = seen.get(d.pattern_id) if d.pattern_id else None
        if d.materialised and prior:
            materialised_with_prior += 1
        if d.pattern_id and d.pattern_id not in seen:
            seen[d.pattern_id] = d.decision_id
        rows.append({
            "decision_id": d.decision_id,
            "idx": d.idx,
            "date": d.date.date().isoformat(),
            "domain": d.domain,
            "decision_type": d.decision_type,
            "pattern_id": d.pattern_id,
            "outcome": d.outcome,
            "materialised": d.materialised,
            "is_mirror": d.is_mirror,
            "precedent_derivable": prior is not None,
            "precedent_decision_id": prior,
        })
    materialised = sum(1 for d in decisions if d.materialised)
    return {
        "decisions": rows,
        "totals": {
            "decisions": len(decisions),
            "materialised": materialised,
            "materialised_with_prior": materialised_with_prior,
            "derivable_coverage": (materialised_with_prior / materialised) if materialised else 0.0,
        },
    }
