# Demo — video script, content deliverables

One build day, one video day. This file is the video day. Follow the timings.

## Video: 3:00 total, five beats

The 4h replay is pre-run and cached (`data/replay.json`). Nothing on camera depends on a live LLM
finishing in time. Record 2-3 takes of the whole thing; the only beats worth a second take are 3 and 4.

### Beat 0 — cold open (0:00-0:20)

**Visual:** the 5-year-old blocks story from the README, on screen as plain text, or narrated over a
simple animation of falling blocks if you have 10 spare minutes. Cheapest version that still works:
narrate it over the app sitting idle.

**Narration (verbatim, from README):**
> Imagine you build towers with blocks. Every time a tower falls, a robot writes down why in a notebook.
> Now before you build a new tower, the robot checks the notebook and says: "a tower like this fell twice.
> Both times the heavy block was on top. Put it at the bottom this time."
> That's the whole idea. And when it has never seen your tower, it says "I don't know this one."

### Beat 1 — the problem, with memory off (0:20-0:50)

**Visual:** the web UI on `:3000`, `MEMORY=off`, preset A loaded (payments-service, config-only,
pool 40 -> 20).

**Action:** click Assess.

**On screen:** generic output — "review for risk, ensure rollback plan, monitor metrics."

**Narration:**
> This is what you get today. A checklist. Nothing here is checkable, and nothing here knows that we have
> broken this exact service this exact way before.

### Beat 2 — memory on, cited precedents (0:50-1:35)

**Visual:** toggle `MEMORY=on`, same preset, same click.

**On screen:** three precedent cards. Top card `L-2026-0412`: config-only, pool size reduced alone,
p99 210ms -> 1.9s, `HikariPool-1 Connection is not available`, proof 2 with `strengthening` badge.

**Narration:**
> Same question, same change, and now it's arguing from our own history. Three precedents, cited by launch
> ID. The top one is a config-only pool change on payments-service, and this flag is marked strengthening,
> which means it has been getting worse, not better.

### Beat 3 — the flip detail (1:35-2:15) *[record twice]*

**Visual:** the flip detail line, then the diff of the two records side by side (breaking vs clean mirror).

**On screen:** *"L-2026-0412 also raised `max_overflow` in the same commit. Yours does not. That parameter
is the difference between the incident and the clean launch."*

**Narration:**
> Here's the part that isn't similarity search. It doesn't just say "this looks similar". It tells me the
> one parameter that differed between the launch that broke and the near-identical one that didn't.
> Same pool change, but max_overflow was raised alongside it, so nothing broke. Mine doesn't raise it.
> The fix is quoted from the postmortem.

### Beat 4 — refusing to guess (2:15-2:45) *[record twice]*

**Visual:** preset C (infra-change, region move, no precedent). Click Assess.

**On screen:** `no precedent`, risk unknown, coverage 79%, plus two nearest-but-insufficient precedents with
the reason each was declined.

**Narration:**
> And when there's nothing to learn from, it says so. Region move, no parameter change, no precedent in our
> history. It reports its own coverage and shows me the two launches it looked at and declined. It doesn't
> stretch an analogy to fill the silence, and that's the whole point.

### Beat 5 — the ledger and close (2:45-3:00)

**Visual:** sidebar ledger: 4 flags, 3 ignored, 2 cost an incident; promoted class `config-only`; then the
memory-growth chart from `get_memories_timeseries`.

**Narration:**
> It also remembers when I didn't listen. Four flags, three ignored, two of those cost an incident. So now
> config-only changes on payments are the first thing it leads with.
> That's the whole thing: a memory that argues with me before I ship, and knows when to shut up.

## Shot list (record in this order, saves screen state juggling)

| # | Shot | State needed |
|---|---|---|
| 1 | Sidebar + bank stats + ledger | seeded bank |
| 2 | Preset A, memory off | toggle off |
| 3 | Preset A, memory on, three cards | toggle on |
| 4 | Click top card, expand source chunk | — |
| 5 | Flip detail + side-by-side records | scroll |
| 6 | Preset A with ledger promoted (card order changed) | ledger seeded |
| 7 | Preset B (P3) | — |
| 8 | Preset C, no precedent + declined list | — |
| 9 | Prompt preview panel (`preview_prompt`) | strong for technical judges: the literal assembled prompt |
| 10 | Memory growth chart | `get_memories_timeseries` |
| 11 | Replay chart: precision + coverage by epoch | `replay.json` |

Shot 9 is optional but cheap and lands hard with a judge who suspects hand-waving: the literal assembled
prompt with mission, directives, disposition, and the recalled memories visible.

## Article (content guide deliverable)

Lead with what is new, not with what you built.

1. **Hook:** pre-mortems get run by hand in slide decks. The knowledge already exists in launch history.
2. **The insight:** similarity is the easy half; the value is the *difference*. Explain flip-detail
   extraction with the P1 example (same pool change, `max_overflow` is the difference).
3. **The second insight:** an agent that remembers its own ignored advice. 4 flags, 2 cost incidents,
   so the promoted class leads the next answer.
4. **How Hindsight is doing the work:** observations with proof counts as confidence, freshness trends as
   the "this is getting worse" badge, `query_timestamp` for honest replay, directives to make refusal
   enforceable, `disposition` literalism 5 so it reads the diff as written.
5. **The honesty section:** report *derivable* coverage vs *found* coverage and admit the gap. Print the
   ground truth. This section is what makes the post credible rather than promotional.
6. **Generalisation:** lookalike over your own history plus an ignored-warning ledger works for compliance
   reviews, medical protocols, legal precedent.

## Social posts (per team member, short)

> Built a pre-mortem agent: it remembers every change our org shipped, what broke, and the ONE parameter
> that flipped the outcome. 4h build, Hindsight as the memory layer.
> The bit I'm proudest of: it says "no precedent" instead of guessing.

Second variant, for the ledger angle:

> Our agent remembers the warnings we ignored. 4 flags, 2 cost incidents. Now it leads with that class.
> Memory isn't just recall. It's calibration.

## Short cut (30-45s)

Beats 0, 2, 3, 4 compressed. Same narration, cut to the flip detail and the refusal. Post with the article.

## If a judge asks about the stack

Answer plainly, it reads as competence rather than improvisation:

> Hindsight runs self-hosted from the FOSS image because Cloud pins the extraction model, and we wanted the
> whole system on one provider. Hindsight drives 9Router, our existing gateway, on a combo model with
> automatic fallback, and embeds locally. The product UI is Next.js on top of a FastAPI service that owns
> every memory call. Nothing here calls a third-party AI API directly.

Then offer them the Control Plane on `:9999` if they want to poke the banks themselves.

## Live demo (judges)

Same three presets in the same order as the video. If a judge asks to type their own change: accept, and if
it lands in `no_precedent` say so confidently — that is the feature, not a failure. Never improvise a
different narrative under pressure; fall back to the presets.
