# Demo — video script, shot list, content deliverables

One build day, one video day. This file is the video day.

## The product in one line

You describe a business decision you are considering. It searches what your company actually did before,
flags what went wrong, and cites every past decision by id. No precedent means it says so.

## Visual language (so the shots match the product)

Warm paper, serif headlines, hairline rules. One terracotta accent. **Risk colour is the only saturated
colour on screen**, so when something is red it always means the same thing. The evidence sits as a
footnote apparatus, not as competing panels. Shoot against this, not against a dashboard aesthetic.

The page is light by default and follows your system theme; dark mode is a warm inversion, not grey.
Context (calibration, engine detail, settings) lives in a collapsible drawer behind the panel icon at the
left of the masthead, so the reading column stays clean. **Open the drawer on camera at least once** — it
is where the theme control, the evidence toggle, and the calibration numbers live.

## Video: 3:00 total, five beats

The review streams, so beats 2 and 3 are naturally cinematic: the text types itself out and the risk
banner lands before the prose. Rehearse the timing so you do not talk over the reveal.

### Beat 0 — cold open (0:00-0:22)

**Visual:** the 5-year-old explainer, narrated over the empty editorial page (the serif headline and the
three "Try one" rows).

**Narration (verbatim from the README):**
> Imagine your company is a person who has made a lot of decisions. Some worked, some went badly.
> Right now that person has no memory, so when you ask "should we give this customer a big discount?",
> nobody remembers you did that twice before and it hurt both times.
> This is a notebook for the company. And when it has never seen your decision, it says "I don't know
> this one" — which is what makes it not a liar.

### Beat 1 — the problem (0:22-0:42)

**Visual:** the empty page, cursor in the composer at the bottom.

**Narration:**
> Every company has made the same mistake twice. The knowledge exists, in decisions people already took.
> It is just not retrievable before you decide again. So people ask an AI, and the AI gives them a
> generic opinion with no idea what this company has already lived through.

### Beat 2 — ask, and watch it work (0:42-1:35)

**Visual:** click the first "Try one" row. Let the stream run. Point at the stage line changing —
*classifying the decision… recalling past decisions… writing the review…* — then the prose typing itself.

**Prompt A:**
> "Acme's renewal is at risk and their champion is asking for a gesture because a competitor came in
> cheaper. I want to give them a 30 percent discount to close it this quarter. Should I?"

**On screen, in order:** `High risk 0.79` + the rule line → the Laya strip → the streamed headline.

**Narration:**
> It classified the decision locally first — no API call, that is a 421-million-parameter model running
> in our own container. Then it searched our history. Then it wrote this.
> "Do not give the 30 percent discount as proposed — an untied 30 percent is the exact shape that cost us
> 6.2 points of gross margin in both D-2025-0002 and D-2025-0013."

### Beat 3 — the difference (1:35-2:20) *[record twice]*

**Visual:** scroll to the terracotta **THE DIFFERENCE** block at the margin, then the source pills:
`D-2025-0002` (evidence 2), `D-2025-0013` (went badly), `D-2025-0023` (near-identical, went fine).
**Hover one pill** to show the preview card, then **click it** to expand the full record. Every id named in
the prose is the same pill, so a claim and its evidence are the same object on screen. The evidence list is
collapsed by default — that is deliberate, not a bug.

**On screen:** *"The uncommitted 30 percent in D-2025-0013 went bad; the near-identical 30 percent in
D-2025-0023 went fine, and the only recorded difference is that D-2025-0023 was 'in exchange for a 3-year
term commitment and a 250-seat volume floor.'"*

**Narration:**
> Here is the part that is not a similarity search. It found two decisions that look identical on every
> dimension, one that went badly and one that went fine, and named the one thing that differed: the term
> commitment. That is the answer to "should I do this" — not a risk score, a condition.
> Every id is a real past decision and every claim is quoted from the record.

### Beat 4 — refusing to guess (2:20-2:50) *[record twice]*

**Visual:** click the third row: *"We are considering opening an office in Lisbon."*

**On screen:** `No precedent`, no confidence number, zero citations, the "considered and declined" list,
and then the fenced **"If I had to guess"** panel: `low confidence`, a general-practice paragraph, and three
things that would change the decision.

**Narration:**
> And when our history has nothing, it says so. No precedent, no confident answer, no stretched analogy.
> It shows what it looked at and declined.
> Then, separately and clearly labelled, it will tell you what general practice says — marked low
> confidence, forbidden from citing anything, because a guess dressed up as a citation would destroy the
> only thing that makes this worth trusting. Restraint is the feature; the guess is the consolation prize,
> and you can always tell them apart.

### Beat 5 — the ledger and close (2:50-3:00)

**Visual:** open the context drawer (panel icon, left of the masthead). Calibration reads **warnings
raised 5 · ignored anyway 4 · of those, cost something 3**, with the three promoted classes beneath and the
decisions themselves expandable below that.

**Narration:**
> It also remembers when we were warned and did it anyway. Five warnings raised, four ignored, three of
> those cost us. So those classes are what it leads with now.
> A memory that argues with you before you decide, and knows when to shut up.

## Shot list (record in this order)

| # | Shot | State needed |
|---|---|---|
| 1 | Masthead, then open the drawer: theme control, calibration, status with the check mark | seeded banks |
| 2 | Empty state: serif headline, the five "Try one" rows, "How it works" aside | live API |
| 3 | Preset A clicked, stage line advancing | live API |
| 4 | Streamed headline appearing (let it type, do not cut) | live API |
| 5 | Risk line close-up: `High risk 0.79` + the rule sentence | live API |
| 6 | Laya strip: 97% certainty, reversibility, value given away | live API |
| 7 | THE DIFFERENCE block (terracotta, at the margin) | live API |
| 8 | MAKE IT SAFE line | live API |
| 9 | CONFIRM FIRST questions | live API |
| 10 | Citation list: three ids, evidence counts, outcome labels | live API |
| 11 | "also considered and declined" expanded | live API |
| 12 | Preset C: `No precedent` + declined list | live API |
| 13 | Preset B: hiring, `High risk`, bad precedents | live API |
| 14 | Drawer open: calibration numbers + promoted classes | — |
| 15 | `/health` showing `laya: loaded true` (technical judges) | live API |
| 16 | A decision typed from scratch that returns `No precedent` | live API |
| 17 | Pill hover preview, then expanded full record | live API |
| 18 | Toggle the theme to dark, then back to system | — |
| 19 | Preset D: `compliance`, citing the reopened finding + its mirror | live API |
| 20 | Preset E: `partnership`, citing the exclusivity loss + its mirror | live API |

Shot 16 matters: it proves the thing is not scripted. Type a decision the corpus does not cover and let it
refuse on camera.

## If a judge asks about the stack

> Hindsight runs on Vectorize Cloud and holds the memory. Our own prose calls go to OpenCode Go, our
> existing gateway. Classification is local: Laya, a 421-million-parameter System One model, ONNX int4,
> about a gig of RAM, no API call and no per-request cost. The UI is Next.js streaming server-sent events
> from a FastAPI service that owns every memory call.

Then the honest caveat, which reads as competence rather than weakness:

> Laya is not the decision-maker. It classifies and gates. The verdict comes from the recorded outcomes of
> our own past decisions, computed by a deterministic ranker. The model only writes the sentences.

If they ask about the design: it is deliberately editorial, because the product is a document you read
before deciding, not a dashboard you monitor.

## Article (content guide deliverable)

Lead with what is new, not with what you built.

1. **Hook:** every company has made the same mistake twice. The knowledge exists; it is just not
   retrievable before you decide again.
2. **Insight one:** similarity is the easy half. The value is the *difference* — the one detail that
   separated a decision that went badly from a near-identical one that went fine. Use the Acme example.
3. **Insight two:** an agent that remembers its own ignored warnings. 4 of 5 ignored, 3 cost something, so
   it now leads with those classes.
4. **How Hindsight does the work:** observations with proof counts as the evidence number, freshness trends
   as the "this is getting worse" signal, directives to make refusal enforceable, disposition literalism 5.
5. **The honesty section:** `query_timestamp` does not filter on this API version, so no-lookahead is our
   own `occurred_start` filter. Consolidated observations carry empty metadata, so every cited id is
   cross-checked against the corpus before it is quoted. Report the derivable-vs-found coverage gap. This
   section is what makes the post credible instead of promotional.
6. **Where a small local model fits:** Laya replaces a paid classification call with a calibrated one and
   adds a reversibility signal. State its measured accuracy (67.3% vs 59.6% on 108 cases) rather than
   claiming it beats an LLM at everything.
7. **Generalisation:** the same shape works for compliance reviews, clinical protocols, and legal precedent.

## Social posts (per team member, short)

> Built a pre-mortem for business decisions: describe what you're about to do, and it searches what your
> company actually did before, flags what went wrong, and cites every past decision by id.
> The bit I'm proudest of: when there's no precedent it says so instead of guessing.

Second variant, for the ledger angle:

> Our reviewer remembers the warnings we ignored. 4 of 5 ignored, 3 cost us. Now it leads with those
> classes. Memory isn't just recall — it's calibration.

## Short cut (30-45s)

Beats 0, 2, 3, 4 compressed. Same narration, cut to the streamed headline, the difference, and the refusal.

## Live demo (judges)

Same five presets in the same order as the video (A, B, C, D, E). If a judge types their own decision: accept it. If it
lands in `No precedent`, say so confidently — that is the feature, not a failure. Never improvise a
different narrative under pressure; fall back to the presets.
