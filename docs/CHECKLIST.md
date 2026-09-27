# Checklist

Two days. Day 1 build, day 2 video + content. Tick in order, nothing out of sequence.

## Before anything (10 min)

- [ ] Hindsight Cloud account created, promo `MEMHACK99` applied in billing (adds $50 credits)
- [ ] Bank created, `HINDSIGHT_API_KEY` in `.env` (gitignored)
- [ ] Groq key in `.env`, model set to `openai/gpt-oss-120b`
- [ ] `pip install hindsight-client streamlit` (venv, PEP 668 means no system install)
- [ ] `banks.test_bank_llm(bank_id)` passes — fails fast if the bank's LLM is unreachable

## Day 1 — build, 4h

- [ ] `seed.py`: 40 launches, 6 services, ~14 months, all 6 patterns from `docs/DATA.md`, including the
      clean mirrors. **Protect this block, it is the project.**
- [ ] `seed.py` writes `data/ground_truth.json` from the pattern table, not from the LLM
- [ ] `retain_batch` the corpus with `timestamp` = launch date and `metadata` = launch ID / service /
      change class / pattern / outcome
- [ ] `banks.recover_consolidation(bank_id)` then assert observations exist with proof counts >= 2
- [ ] Bank config: mission, 5 directives, disposition 4/5/2 — then `get_bank_config` and print it
- [ ] `lookalike.py`: `recall_precedents` with `query_timestamp`, deterministic `rank`, `MIN_PROOF` gate
- [ ] `reflect(response_schema=FLIP_SCHEMA)` for flip-detail extraction, `include_facts=True`
- [ ] `no_precedent` path returns coverage % plus the two nearest declined precedents
- [ ] `ledger.py`: 4 flags, 3 ignored, 2 costed, promoted class feeds `rank(prefer=...)`
- [ ] `app.py`: one screen, three presets, `MEMORY=on/off` toggle, precedent cards with proof + trend,
      flip detail, sidebar ledger + bank stats, prompt preview button, consolidation button
- [ ] `replay()` run over all 40 launches, cached to `data/replay.json`
- [ ] `tests/run_all.py`: asserts on preset A returns a precedent, preset C returns `no_precedent`,
      ledger promotion changes preset A's top card, ground-truth totals match the corpus
- [ ] **Freeze the real precision/coverage numbers** into `PLAN.md` and the README. Do not tune the write-up
      to match a target; tune `MIN_PROOF` or corpus density, then re-run

## Pre-record (30 min, do not skip)

- [ ] Fresh seed, then `recover_consolidation`, then confirm observations visible in the UI
- [ ] `test_bank_llm` passes
- [ ] All three presets exercised end to end, twice
- [ ] `data/replay.json` present so the metric charts render instantly
- [ ] Prompt preview renders without cutting off
- [ ] Streamlit restarted, cache cleared, browser zoom fixed, notifications silenced, other tabs closed
- [ ] Terminal font size up; no secrets visible on screen (check the sidebar for the API key)
- [ ] Recording tool set to 1080p, mic tested, 20 seconds of silent room tone captured for edits

## Day 2 — video + content

- [ ] Beats 0-5 recorded per `docs/DEMO.md`, beats 3 and 4 with a second take
- [ ] Subtitle burn-in (judges often watch muted)
- [ ] 3:00 cut assembled; 30-45s short cut assembled
- [ ] Article written per the outline in `docs/DEMO.md`, honesty section included (derivable vs found coverage)
- [ ] Per-member social post, both variants considered, one posted each
- [ ] Video uploaded, link verified in an incognito window (private links are a classic submission killer)

## Submission

- [ ] Repo flipped from private to public
- [ ] README: setup, the 5-year-old explainer, a "How Hindsight is used" section naming
      `retain` / `recall(query_timestamp)` / `reflect(response_schema)` / observations with proof counts and
      freshness trends / `directives` / `disposition` / `recover_consolidation` / `get_memories_timeseries`
- [ ] Architecture diagram or the ASCII tree from `docs/ARCHITECTURE.md` in the README
- [ ] `.env.example` committed, `.env` confirmed untracked (`git status --porcelain` clean of secrets)
- [ ] Demo video link in the README and in the submission form
- [ ] Live demo rehearsed twice against a fresh seed
- [ ] One paragraph stating exactly how Hindsight memory is used, per the submission requirement

## Honest-framing gates (any failure here costs the memory score)

- [ ] Every claim on screen carries a launch ID, a proof count, or a coverage number
- [ ] The LLM never produces the risk verdict; `rank()` does, and `rank()` is shown in the UI
- [ ] Contradiction case (clean mirror for P1) is visible, not buried
- [ ] `no_precedent` shown at least once on camera, with coverage stated
- [ ] The derivable-vs-found coverage gap is reported even if it looks worse
- [ ] No sentence anywhere implies the tool ships, approves, or deploys anything
