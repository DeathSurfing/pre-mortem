"""Richer half of the company decision history.

The base corpus (bizcorpus.PLAN, 36 decisions) proves the mechanism. This half makes the scenario feel like
a real company: every decision gains an owner, an amount at stake, and the market context of the moment, and
it adds four decision areas the base corpus did not cover (compliance, security, partnerships, regions).

Why it matters for the demo: recall quality depends on how much distinctive detail the memory holds. A
one-line decision retrieves on keyword overlap; a decision with an owner, a figure, and a context retrieves
on the situation. The detail is also what makes the citations checkable by a judge.

Structure mirrors the base corpus exactly:
    EXTRA_PLAN      (idx, pattern, domain, decision_type, kind)
    EXTRA_CHANGES   pattern -> {"brk": (decision, rationale), "mir": (decision, rationale)}
    EXTRA_LESSONS   pattern -> the recorded lesson
    EXTRA_RESULTS   pattern -> what actually happened
    EXTRA_PLAIN     domain  -> (decision, rationale, result, lesson) for non-pattern decisions
    EXTRA_BREAK_PLAN pattern -> outcome sequence for repeated breaks
    RICH            (domain, decision_type) -> owner / scale / context

idx continues from 36 so decision ids stay D-<year>-00NN and dates keep advancing at the same 14-day step.
"""
from __future__ import annotations

# ---------------------------------------------------------------- owners and scale

# Owner, amount at stake, and the context of the moment, per domain+type. These are what turn a decision
# line into a retrievable situation.
RICH: dict[tuple[str, str], dict[str, str]] = {
    ("pricing", "discount"): {
        "owner": "Priya Raghunathan, VP Revenue",
        "scale": "ARR impact 340k, gross margin 6.2 points on the affected accounts",
        "context": "Two competitors had just published lower list prices and the sales team was losing "
                   "late-stage deals on price rather than on fit.",
    },
    ("pricing", "price-increase"): {
        "owner": "Priya Raghunathan, VP Revenue",
        "scale": "ARR impact 1.1M across 210 accounts",
        "context": "Input costs had risen for three consecutive quarters and the last uplift was 26 months "
                   "earlier, so list price had drifted well behind the market.",
    },
    ("pricing", "packaging"): {
        "owner": "Marcus Bell, Head of Product",
        "scale": "affected 480 accounts on the legacy tiers",
        "context": "Feature usage data showed most accounts were paying for a tier whose defining feature "
                   "they never touched, and the sales team had started discounting around the structure.",
    },
    ("hiring", "senior-hire"): {
        "owner": "Dana Okonkwo, VP Engineering",
        "scale": "fully loaded cost 210k a year, plus 4 months of team ramp",
        "context": "Two consecutive quarters of missed roadmap dates and attrition in the platform team had "
                   "made senior capacity the binding constraint.",
    },
    ("hiring", "backfill"): {
        "owner": "Dana Okonkwo, VP Engineering",
        "scale": "backfill cost 135k a year against a frozen headcount plan",
        "context": "A departure on a critical service left an on-call gap, and the team had been carrying "
                   "extra rotations for six weeks.",
    },
    ("hiring", "contractor-conversion"): {
        "owner": "Dana Okonkwo, VP Engineering",
        "scale": "4 contractors at 95k each, converting to 140k fully loaded",
        "context": "Contractors had been embedded for over a year and were doing work indistinguishable "
                   "from the permanent team's, which was starting to attract scrutiny.",
    },
    ("vendor", "renewal"): {
        "owner": "Tom Nsiah, Head of Procurement",
        "scale": "annual contract 186k, proposed uplift 14 percent",
        "context": "The vendor knew they were embedded in a critical path and had opened the renewal at a "
                   "number well above list.",
    },
    ("vendor", "vendor-switch"): {
        "owner": "Tom Nsiah, Head of Procurement",
        "scale": "migration cost 90k upfront against 240k of annual savings",
        "context": "Two credible alternatives had matured, and the incumbent's roadmap had stopped "
                   "addressing the gaps that mattered to us.",
    },
    ("marketing", "budget-shift"): {
        "owner": "Sofia Marchetti, Head of Growth",
        "scale": "320k of quarterly spend reallocated from paid search to events",
        "context": "Paid search cost per qualified lead had doubled in a year while event-sourced pipeline "
                   "was converting better, and the board wanted the mix revisited.",
    },
    ("marketing", "channel-test"): {
        "owner": "Sofia Marchetti, Head of Growth",
        "scale": "60k test budget over one quarter",
        "context": "The two established channels were saturating and the team wanted a third source before "
                   "the next planning cycle.",
    },
    ("launch", "feature-ga"): {
        "owner": "Marcus Bell, Head of Product",
        "scale": "3 engineering squads for a quarter, and a committed launch date",
        "context": "Three large accounts had it written into their renewal terms and the sales team had "
                   "started quoting the date publicly.",
    },
    ("buildvsbuy", "build"): {
        "owner": "Dana Okonkwo, VP Engineering",
        "scale": "2 engineers for two quarters, against 120k a year for the vendor option",
        "context": "The vendor's licensing model would have made cost scale with our success, and the team "
                   "believed the integration was simpler than the vendor claimed.",
    },
    ("buildvsbuy", "buy"): {
        "owner": "Dana Okonkwo, VP Engineering",
        "scale": "140k a year, replacing an in-house component that had 1 owner",
        "context": "The in-house component worked, but every change to it landed on one engineer and that "
                   "had become a standing risk in review.",
    },
    # ---- areas the base corpus did not cover
    ("compliance", "audit-finding"): {
        "owner": "Rachel Adeyemi, Head of Compliance",
        "scale": "one high-severity finding, with the next audit window 5 months out",
        "context": "The auditor accepted compensating controls in the interim, and the engineering fix "
                   "competed with committed product work for the same two engineers.",
    },
    ("security", "incident-response"): {
        "owner": "Rachel Adeyemi, Head of Compliance",
        "scale": "48 minutes of degraded auth for 9 percent of sessions, one customer escalation",
        "context": "The on-call runbook covered the service but not the shared dependency, and the "
                   "post-incident review had flagged the same dependency twice before.",
    },
    ("partnership", "reseller-agreement"): {
        "owner": "Priya Raghunathan, VP Revenue",
        "scale": "18 percent margin share on the partner-sourced deals, roughly 260k a year",
        "context": "The partner had access to a segment the direct team could not reach, and asked for "
                   "exclusivity in that segment as part of the terms.",
    },
    ("ops", "datacenter-region"): {
        "owner": "Dana Okonkwo, VP Engineering",
        "scale": "180k a year of added infrastructure, plus a 9-month migration",
        "context": "Two enterprise prospects required in-region data residency, and the existing region "
                   "could not satisfy it under their procurement rules.",
    },
}
_B = "brk"
_M = "mir"

# ---------------------------------------------------------------- new patterns

EXTRA_CHANGES: dict[str, dict[str, tuple[str, str]]] = {
    # B7 compliance
    "B7": {
        _B: ("we closed a SOC 2 finding with a compensating control and deferred the root-cause fix",
             "the fix needed two engineers who were already committed to launch work, and the auditor "
             "had said the interim control was acceptable"),
        _M: ("we closed a SOC 2 finding with a compensating control, with a named owner and a dated "
              "remediation milestone recorded in the audit response",
              "the control alone had failed before, so this time the interim measure carried a written "
              "owner and a date the auditor could hold us to"),
    },
    # B8 security
    "B8": {
        _B: ("we treated a repeat auth dependency failure as an isolated incident and only patched the "
              "surface symptom",
             "the fix cost a sprint and the dependency had caused two brief degradations without "
             "customer-visible impact"),
        _M: ("we treated a repeat auth dependency failure as a systemic risk and scheduled the underlying "
              "replacement into the next quarter",
              "two prior occurrences had already been logged in the post-incident reviews, so leaving the "
              "cause in place meant a third was only a matter of time"),
    },
    # B9 partnership
    "B9": {
        _B: ("we gave a reseller segment exclusivity to close the agreement quickly",
             "they were the only partner with reach into that segment and legal expected the term to be "
             "harmless because we had no coverage there anyway"),
        _M: ("we gave a reseller segment exclusivity with a volume floor and a 12-month review date",
              "exclusivity without a performance floor had cost us optionality before, so this version "
              "had to earn its renewal"),
    },
    # B10 ops
    "B10": {
        _B: ("we stood up a new region for two prospects without a committed contract",
             "procurement had indicated they were close to signing and we did not want to be the reason "
             "the deal slipped"),
        _M: ("we stood up a new region against a signed letter of intent with a dated commitment",
              "the same build-out shape had been done before on a verbal signal and the capacity then sat "
              "idle, so this one waited for something in writing"),
    },
}

EXTRA_LESSONS: dict[str, str] = {
    "B7": "An interim control without a named owner and a dated milestone does not get remediated. "
          "Same finding reopened on the next audit.",
    "B8": "A dependency that has failed twice will fail a third time. A surface patch does not reduce the "
          "probability, it only postpones the exposure.",
    "B9": "Exclusivity without a volume floor transfers all the optionality to the partner. Include a floor "
          "and a review date, or expect to renegotiate from a weak position.",
    "B10": "Regional build-out on a verbal signal leaves paid-for capacity idle. Wait for a signed "
           "commitment before committing infrastructure.",
}

EXTRA_RESULTS: dict[str, str] = {
    "B7": "The finding reopened at the next audit. Two quarters of the remediation window had been spent "
          "on launch work and the interim control had no owner on record.",
    "B8": "A third failure of the same dependency took auth down for 40 minutes during business hours, with "
          "customer-visible impact and an escalation.",
    "B9": "The partner underperformed against expectations for three quarters and we could not replace them "
          "in that segment or sell into it directly.",
    "B10": "One of the two prospects signed. The second stalled in procurement for four months and the "
           "region's committed spend ran at a fraction of the provisioned cost.",
}

EXTRA_PLAIN: dict[str, tuple[str, str, str, str]] = {
    # compliant, non-pattern decisions: the boring majority that makes the history realistic
    "compliance": ("we ran the annual access review in the existing spreadsheet process",
                   "it had passed the last two audits and replacing the tooling was not funded",
                   "Passed review with no findings. Took six weeks of analyst time, which was already "
                   "budgeted.", ""),
    "security": ("we rotated the shared credentials flagged in the quarterly review",
                 "the rotation was overdue and the process was documented",
                 "Completed with no service interruption. Two stale integrations broke and were fixed the "
                 "same day.", ""),
    "partnership": ("we renewed the existing co-marketing agreement with no changes",
                    "both sides were satisfied and the effort was low",
                    "Renewed. Sourced pipeline was broadly flat year on year.", ""),
    "ops": ("we added a read replica in the existing region to absorb reporting load",
            "reporting queries were contending with transactional traffic at peak",
            "Peak p95 on transactional queries recovered to the previous quarter's level.", ""),
}

# ---------------------------------------------------------------- plan (idx 36-71)

# Same shape as the base PLAN: (idx, pattern, domain, decision_type, kind).
EXTRA_PLAN: list[tuple[int, str | None, str, str, str]] = [
    (36, None, "compliance", "audit-finding", "plain"),
    (37, "B1", "pricing", "discount", "brk"),
    (38, "B7", "compliance", "audit-finding", "brk"),
    (39, None, "security", "incident-response", "plain"),
    (40, None, "hiring", "senior-hire", "plain"),
    (41, "B3", "vendor", "vendor-switch", "brk"),
    (42, "B8", "security", "incident-response", "brk"),
    (43, None, "marketing", "channel-test", "plain"),
    (44, "B4", "marketing", "budget-shift", "brk"),
    (45, "B9", "partnership", "reseller-agreement", "brk"),
    (46, None, "ops", "datacenter-region", "plain"),
    (47, "B2", "hiring", "senior-hire", "brk"),
    (48, None, "pricing", "price-increase", "plain"),
    (49, "B10", "ops", "datacenter-region", "brk"),
    (50, "B5", "launch", "feature-ga", "brk"),
    (51, None, "vendor", "renewal", "plain"),
    (52, None, "buildvsbuy", "buy", "plain"),
    (53, "B6", "buildvsbuy", "build", "brk"),
    (54, "B1", "pricing", "discount", "mir"),
    (55, None, "compliance", "audit-finding", "plain"),
    (56, "B2", "hiring", "contractor-conversion", "brk"),
    (57, None, "partnership", "reseller-agreement", "plain"),
    (58, "B3", "vendor", "renewal", "brk"),
    (59, None, "launch", "feature-ga", "plain"),
    (60, "B4", "marketing", "channel-test", "brk"),
    (61, None, "security", "incident-response", "plain"),
    (62, "B7", "compliance", "audit-finding", "mir"),
    (63, None, "hiring", "backfill", "plain"),
    (64, "B5", "launch", "feature-ga", "mir"),
    (65, None, "pricing", "packaging", "plain"),
    (66, "B8", "security", "incident-response", "mir"),
    (67, None, "vendor", "vendor-switch", "plain"),
    (68, "B9", "partnership", "reseller-agreement", "mir"),
    (69, None, "marketing", "budget-shift", "plain"),
    (70, "B10", "ops", "datacenter-region", "mir"),
    (71, None, "buildvsbuy", "build", "plain"),
]

# Break counts per pattern, so repeated occurrences of the same shape resolve differently over time.
EXTRA_BREAK_PLAN: dict[str, list[str]] = {
    "B1": ["bad"],
    "B2": ["bad"],
    "B3": ["bad"],
    "B4": ["bad", "bad"],
    "B5": ["mixed"],
    "B6": ["bad"],
    "B7": ["bad"],
    "B8": ["bad"],
    "B9": ["bad"],
    "B10": ["bad"],
}

# Two more demo prompts, both anchored in the newly covered areas, so the extra corpus is exercised on
# camera rather than only existing in storage.
EXTRA_PROMPTS: list[dict[str, str]] = [
    {
        "key": "D",
        "label": "close an audit finding with a stopgap",
        "text": "Our latest SOC 2 audit raised a finding and the proper fix needs two engineers we have "
                "already committed to launch work. I want to close it with a compensating control and "
                "schedule the real fix for next year. Is that acceptable?",
        "expect_domain": "compliance",
        "expect_type": "audit-finding",
        "expect": "cites the reopened finding, names the missing owner and date on the interim control",
    },
    {
        "key": "E",
        "label": "exclusive reseller deal",
        "text": "A partner with reach into a segment we cannot cover is asking for exclusivity in "
                "exchange for carrying us. I want to sign it quickly because they are the only credible "
                "route into that market. What has burned us on deals like this before?",
        "expect_domain": "partnership",
        "expect_type": "reseller-agreement",
        "expect": "cites the exclusivity loss, names the volume floor and review date as the difference",
    },
]
