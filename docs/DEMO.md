# Demo — video script, shot list, content deliverables

One build day, one video day. This file is the video day.

## The product in one line

You describe a business decision you are considering. It searches what your company actually did before,
flags what went wrong, and cites every past decision by id. No precedent means it says so.

## Video: 3:00 total, five beats

The stream is live, so beats 2 and 3 are naturally cinematic: the answer types itself out. Rehearse the
timing once so you do not talk over the reveal.

### Beat 0 — cold open (0:00-0:22)

**Visual:** the 5-year-old explainer from the README, narrated over the app sitting idle.

**Narration (verbatim from the README):**
> Imagine your company is a person who has made a lot of decisions. Some worked, some went badly.
> Right now that person has no memory, so when you ask "should we give this customer a big discount?",
> nobody remembers you did that twice before and it hurt both times.
> This is a notebook for the company. And when it has never seen your decision, it says "I don't know
> this one" — which is what makes it not a liar.

### Beat 1 — the problem (0:22-0:42)

**Visual:** the empty chat window, cursor in the box.

**Narration:**
> Every company has made the same mistake twice. The knowledge exists, in decisions people already took.
> It is just not retrievable before you decide again. So people ask an AI, and the AI gives them a
> generic opinion with no idea what this company has already lived through.

### Beat 2 — ask, and watch it work (0:42-1:35)

**Visual:** type (or click) the discount prompt. Let the stream run. Point at the stage text changing:
*classifying the decision… recalling past decisions… writing the review…* then the text typing itself.

**Prompt A:**
> "Acme's renewal is at risk and their champion is asking for a gesture because a competitor came in
> cheaper. I want to give them a 30 percent discount to close it this quarter. Should I?"

**On screen, in order:** risk banner `high 0.79` → Laya panel → streamed headline.

**Narration:**
> It classified the decision locally first — no API call, that is a 421-million-parameter model running
> in the container. Then it searched our own history. Then it wrote this.
> "Do not give the 30 percent discount as proposed — an untied 30 percent is the exact shape that cost us
> 6.2 points of gross margin in both D-2025-0002 and D-2025-0013."

### Beat 3 — the difference (1:35-2:20) *[record twice]*

**Visual:** scroll to the `the difference` block, then open the evidence drawer and show the three cards:
`D-2025-0002` (evidence 2), `D-2025-0013` (bad), `D-2025-0023` (near-identical, went fine).

**On screen:** *"D-2025-0013 and D-2025-0023 are the near-identical pair — both were a 30 percent Acme
renewal discount taken 'to protect the quarter, counter a cheaper competitor, and fulfill a request from
the champion', and the single difference is that D-2025-0023 came 'in exchange for a 3-year term
commitment and a 250-seat volume floor'."*

**Narration:**
> Here is the part that is not a similarity search. It found two decisions that look identical on every
> dimension, one that went badly and one that went fine, and named the one thing that differed: the term
> commitment. That is the answer to "should I do this" — not a risk score, a condition.
> Every id is clickable and every claim is quoted from the record.

### Beat 4 — refusing to guess (2:20-2:50) *[record twice]*

**Visual:** click the third preset: *"We are considering opening an office in Lisbon."*

**On screen:** `no precedent`, confidence `—`, zero precedent cards, and the declined list.

**Narration:**
> And when our history has nothing, it says so. No precedent, no confident answer, no stretched analogy.
> It shows what it looked at and declined. Restraint is the feature.

### Beat 5 — the ledger and close (2:50-3:00)

**Visual:** the ledger bar at the top: `4 of 5 past warnings were ignored, 3 of those cost something`, and
the promoted classes `pricing@discount`, `hiring@senior-hire`, `marketing@budget-shift`.

**Narration:**
> It also remembers when we were warned and did it anyway. Four of five warnings ignored, three of those
> cost us. So those classes are what it leads with now.
> A memory that argues with you before you decide, and knows when to shut up.

## Shot list (record in this order)

| # | Shot | State needed |
|---|---|---|
| 1 | Empty chat window + ledger bar + `laya ready` | seeded banks |
| 2 | Preset A: type/click, stage text advancing | live API |
| 3 | Streamed headline appearing (let it type, do not cut) | live API |
| 4 | Laya panel close-up: 97% certainty, reversibility, value given away | live API |
| 5 | `the difference` block | live API |
| 6 | Evidence drawer open: 3 cards with evidence counts and the mirror badge | live API |
| 7 | `make it safe` guardrail line | live API |
| 8 | Open questions list | live API |
| 9 | Preset C: `no precedent` + declined list | live API |
| 10 | Preset B: hiring, `high 0.67`, two bad precedents | live API |
| 11 | Ledger bar close-up | — |
| 12 | `/health` showing `laya: loaded true` (technical judges) | live API |
| 13 | A second, typed-from-scratch prompt to prove it is not canned | live API |

Shot 13 matters: it proves the thing is not scripted. Pick a decision the corpus does cover and one it
does not, and let the second one return `no precedent` on camera.

## If a judge asks about the stack

> Hindsight runs on Vectorize Cloud and holds the memory. Our own prose calls go to OpenCode Go, our
> existing gateway. Classification is local: Laya, a 421-million-parameter System One model, ONNX int4,
> about a gig of RAM, no API call and no per-request cost. The UI is Next.js streaming server-sent events
> from a FastAPI service that owns every memory call.

Then the honest caveat, which reads as competence rather than weakness:

> Laya is not the decision-maker. It classifies and gates. The verdict comes from the recorded outcomes of
> our own past decisions, computed by a deterministic ranker. The model only writes the sentences.

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
   own `occurred_start` filter. Report the derivable-vs-found coverage gap. Also: consolidated observations
   carry empty metadata, so every cited id is cross-checked against the corpus before it is quoted. This
   section is what makes the post credible instead of promotional.
6. **Where a small local model fits:** Laya replaces a paid classification call with a calibrated one and
   adds a reversibility signal. State its measured accuracy (67.3% vs 59.6% on 108 cases) rather than
   claiming it is better than an LLM at everything.
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

Same three presets in the same order as the video. If a judge types their own decision: accept it. If it
lands in `no precedent`, say so confidently — that is the feature, not a failure. Never improvise a
different narrative under pressure; fall back to the presets.
