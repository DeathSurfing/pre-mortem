# pre-mortem — full plan

Internal working doc. Two days total: 1 day build, 1 day video + content deliverables.
Idea: **Change-Risk Lookalike Memory.** Repo name `pre-mortem`.

Tagline: *Your deploy history, argued back at you before you ship.*

## The problem, stated so judges feel it

Every org runs change review by hand. Someone reads a diff, thinks "this looks like the time we broke
checkout", and either remembers the detail or does not. When they do not, the same class of change breaks
the same service again, and the postmortem says "this has happened before" with nothing behind it.

The knowledge exists. It is in past launches, past rollbacks, past incident tickets. It is just not
retrievable *prospectively* for a change that has not shipped yet, and no tool remembers the specific
detail that flipped the outcome last time.

## The one-line product

Given a pending change, surface the most similar past changes your org shipped, cite them by launch ID,
name the **one detail that differed** in the cases that broke, give a confidence number derived from
evidence counts, and say `no_precedent` when there is nothing to learn from.

Then remember which warnings were ignored and what they cost, and lead with that class.

## Judging criteria mapping

### Innovation (30%) — "nobody demos this shape"

- The agent does lookalike retrieval over the org's own operational history **for an unshipped change**.
  Prospective, not retrospective. Every other team will demo an agent that remembers users or tickets.
- Real novelty is **flip-detail extraction**: it does not just say "these look similar", it names the one
  parameter difference between the precedent that broke and the near-identical one that did not. That is
  the difference between similarity search and insight.
- The **ignored-warning ledger** is a genuinely uncommon mechanic: the agent recalls its own dismissed
  advice, the cost of each dismissal, and changes what it leads with as a result.
- Pre-mortems are a real practice companies run manually in slide decks. Turning them into an agent with a
  memory of every past launch is a fresh take on a real workflow.

### Use of Hindsight (25%) — memory is the entire product

Remove Hindsight and there is no artifact: no similarity corpus, no confidence numbers, no trend signal,
no ignored-flag history, no honest replay. Load-bearing surface:

| Product element | Hindsight surface |
|---|---|
| Launch history (diff summary, metrics, outcome, fix) | `retain` with `metadata` = launch ID / service / change class |
| Cross-launch consolidation: *"config-only payments deploys broke twice, both times a pool parameter (proof 2, strengthening)"* | `observation` with proof count + freshness trend |
| The confidence number shown in the UI | observation proof count, zero hand-tuning |
| "This failure mode is getting worse" badge | freshness trend `strengthening` / `weakening` / `stale` |
| Precedent cards with exact source text | `recall(include_chunks=True)` |
| Honest replay (launch N cannot see launch N+1) | `recall(query_timestamp=...)` |
| Refusing to assert an uncited cause | `directives` — "never assert a precedent without a cited launch ID", "never state a cause you cannot link to a retained fix" |
| Refusing rather than guessing | `disposition` skepticism 4 / literalism 5 / empathy 2 |
| Instant, identical canned demo answers | `mental_models` |

`query_timestamp` is the load-bearing detail for credibility: the pre-mortem for launch N structurally
cannot see later launches. Lookahead is impossible, not promised.

### Technical implementation (20%) — small, clean, honest

~400 lines across four files. No broker, no third-party API beyond Hindsight + Groq, no auth, no DB.

Edge cases handled on camera, because handling them is what earns this axis:
- **no precedent** -> `no_precedent` response, never a stretched analogy;
- **contradictory precedent** (one launch broke, a near-identical one did not) -> both shown side by side,
  never averaged into a false confidence;
- **cold start** -> coverage reported honestly as low for the first 10 launches;
- **LLM function-calling failure** -> try/except, JSON validate, one repair retry, plain JSON-mode fallback.

### User experience (15%) — one screen, one number, 15-second payoff

Left pane: the pending change diff. Right pane: ranked precedents, each with launch ID, date, proof count,
trend badge, and what happened. Top: one risk number derived from proof counts. Bottom: the flip detail in
one sentence. A `MEMORY=on/off` toggle renders both answers to the same question.

No navigation, no onboarding, nothing to learn. A judge understands the screen before the first sentence of
narration finishes.

### Real-world impact (10%) — real buyer, real budget

Change advisory boards, SRE change-risk review, and pre-mortem sessions exist as job functions today and are
done by hand in slides. Anything that shortens that review gets bought. Adoption path is concrete: a GitHub
Action or CI check before deploy, or a Slack bot in the release channel.

## Metrics (on screen, reproducible from the seed)

```
Flag precision (of risks flagged, how many materialised)      64% -> 88% across the replay
Coverage (share of real incidents with a matching precedent)   31% -> 79%
Cold-start bucket (no precedent found)                         starts high, falls correctly
Ignored-warning ledger                                         4 flags ignored, 2 cost an incident
```

Print the seed's ground truth so a judge can spot-check any single flag. Numbers that cannot be reproduced
from the corpus are the easiest thing to disbelieve.

## 60-second demo script

1. **0-12s** Memory off, paste a pending config-only change to `payments-service`. Generic output: "review
   for risk, ensure rollback plan, monitor metrics." Nothing checkable.
2. **12-30s** Memory on, same change. Three precedents with launch IDs and dates. Top result `L-2026-0412`:
   you also changed only the pool size, latency p99 spiked 4x, root cause `max_overflow` (proof 2,
   `strengthening`). Say: *"last time this exact shape of change broke this service."*
3. **30-42s** The flip detail: the one parameter difference between then and now that changes the outcome,
   citing the fix that resolved it. Say "difference", never "similar".
4. **42-52s** Ask about a change with no precedent. `no_precedent`, coverage stated, no stretched analogy.
   Restraint reads as competence.
5. **52-60s** Counters: precision and coverage climbing, trend badges on two services, ignored-warning
   ledger. Close on the ledger line.

## Data

Synthetic, fully controlled, and **interlocked** or nothing works. 40 launches, 6 services, ~14 months.
Interlocks that give the agent real patterns to discover:
- config-only payments deploys break on pool parameters (`max_overflow`);
- schema migrations cause read-replica lag;
- dependency bumps break auth;
- one clean near-twin for each breaking launch, so flip-detail extraction has something to find and
  contradiction handling has something to show.

Real-sounding service names, real-shaped symptom lines, plausible before/after metrics.

## SWOT

**Strengths** — memory is the corpus, not a feature; the `no_precedent` refusal is the strongest available
anti-black-box evidence; one screen and one number; a real buyer with a real budget; 4h build; flip-detail
extraction is a genuine technical contribution rather than plumbing.

**Weaknesses** — judges may file it as "similarity search over incident history" until they hear the flip
detail and the ignored-warning ledger, so both must land inside the first 30 seconds. Synthetic corpus
quality decides everything; if it is not interlocked the improvement numbers look random. No dramatic visual
(the payoff is a sentence, not a chart).

**Opportunities** — ship as a CI check or Slack bot; extend to "which of our past fixes are about to
regress" using trend badges; the pattern (lookalike over own history + ignored-warning ledger) generalises
to compliance reviews, medical protocols, and legal precedent, which is the article.

**Threats** — reads as another incident agent if you lead with incident data instead of the pending change;
precision/coverage must be reproducible or a skeptical judge will discount everything; scope creep into a
second use case would cost the build day.

## 1-day build order (4h, with buffer)

| Time | Work |
|---|---|
| 0:00-0:30 | Hindsight Cloud bank + key, Groq key, `pip install hindsight-client streamlit`, smoke-test retain/recall/reflect |
| 0:30-1:30 | `seed.py` — 40 interlocked launches, 6 services, realistic symptom lines, outcomes, fixes. Retain with metadata. Settle. **Biggest block, protect it** |
| 1:30-2:15 | `lookalike.py` — recall the pending change, rank by proof count + recency + trend, flip-detail extraction via one `reflect(response_schema=...)` |
| 2:15-2:45 | `ledger.py` — retain ignored flags and their outcomes; make the agent lead with the ignored class |
| 2:45-3:30 | `app.py` — one Streamlit screen: diff left, precedents right, risk number top, flip detail bottom, `MEMORY=on/off` toggle, `no_precedent` state |
| 3:30-4:00 | Bank `mission` / `directives` / `disposition`, 2 `mental_models`, replay the window, freeze the precision/coverage numbers, README + architecture sketch, raw screen capture |

**Cut list, in order if behind:**
1. Flip-detail `response_schema` -> loose JSON parsing.
2. Structured precedent card -> plain text list with launch IDs.
3. 40 launches -> 25. Keep the interlock, lose the volume.
4. Ignored-warning automation -> one hardcoded example, still shown on screen.
5. **Never cut:** `MEMORY=on/off` toggle, proof counts as confidence, `no_precedent` refusal, flip-detail
   line, ignored-warning ledger.

## Day 2 — video and content deliverables

- 3 min video: use the five beats above. Record the flip-detail and `no_precedent` beats twice so there is
  a clean take. The 5-year-old explainer in the README is the 20-second cold open, verbatim.
- Article: lead with the ignored-warning ledger and the flip-detail idea. Include the Hindsight feature
  table, the reproducibility note (print the seed's ground truth), and the `query_timestamp` honesty point.
- Social post per team member, plus a short video cut, per the content guide.
- Submission: private repo made public at submission time, README with setup, a "How Hindsight is used"
  section naming retain / recall with `query_timestamp` / reflect with `response_schema` / observations with
  proof counts and freshness trends / directives / disposition. Demo video link, live demo rehearsed twice,
  one paragraph on memory usage.

## Risks

| Risk | Mitigation |
|---|---|
| Reads as similarity search over incidents | Lead with flip detail and the ignored-warning ledger inside the first 30 seconds; say "difference", not "similar" |
| Reads as another incident agent | Open with the pending change, not with incident history |
| Numbers not reproducible | Print the seed's ground truth, let a judge spot-check one flag |
| Observations not consolidated before recording | Seed early, verify with `client.memories.list`; reflect re-verifies stale observations against raw facts anyway |
| Groq function-calling / JSON errors | try/except, validate, one repair retry, JSON-mode fallback |
| Reflect latency (agentic loop, up to 10 iterations) | `budget="low"`, small `max_tokens`, `mental_models` for the canned demo questions, pre-run the filmed beats |
| Scope creep | One workflow, one persona, one metric. Cut the second use case without negotiating |

## Stated scope

Decision-support only. Reports what happened in the change history, with citations. Does not ship anything,
does not touch production, does not give advice. Synthetic data only.

## Score guess

Innovation 9 (10 if the ignored-warning beat lands on camera) / Memory 10 / Tech 9 / UX 10 / Impact 9.
Innovation is capped by "lookalike over history" being explainable in one phrase; Impact is capped by change
review being a real but unglamorous budget line. Both are the smallest available caps, which is the whole
reason to pick this idea.
