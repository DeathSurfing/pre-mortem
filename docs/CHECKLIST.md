# Checklist

Two days. Day 1 build, day 2 video + content. Tick in order, nothing out of sequence.

## Before anything (50 min) — this block is a gate

- [ ] `.env` from `.env.example`: `OPENCODE_GO_API_KEY` (Go subscription active), `OPENCODE_SESSION`,
      `LLM_MODEL=deepseek-v4.1-flash`, `HINDSIGHT_LLM_MODEL=deepseek-v4-flash`, 9Router fallback vars
- [ ] Hindsight container up with `HINDSIGHT_API_LLM_PROVIDER=opencode-go`,
      `HINDSIGHT_API_EMBEDDINGS_PROVIDER=local` (exact service block in `docs/MODELS.md`)
- [ ] One direct chat call to OpenCode Go with `x-opencode-session` returns a completion (proves the key has
      Go access before blaming Hindsight)
- [ ] `GET :8888/health` responds; Control Plane on `:9999` loads
- [ ] `banks.test_bank_llm(bank_id)` passes
- [ ] One retain -> recall round trip produces an `observation` with a proof count
- [ ] `reflect` with `response_schema` returns structured output through 9Router
- [ ] **If any of the above fails, stop.** Fall back in order: (1) `HINDSIGHT_LLM_MODEL` to a stronger
      OpenCode Go model, (2) whole system to 9Router `gareebi` via `HINDSIGHT_API_LLM_PROVIDER=openai` +
      `_BASE_URL=$NINEROUTER_URL/v1`. Do not start app code on a broken memory layer

## Day 1 — build, 5h

- [ ] `api/app/corpus.py`: 40 launches, 6 services, ~14 months, all 6 patterns from `docs/DATA.md`, including
      the clean mirrors. **Protect this block, it is the project.**
- [ ] `api/app/seed.py` writes `data/ground_truth.json` from the pattern table, not from the LLM
- [ ] `retain_batch` the corpus with `timestamp` = launch date and `metadata` = launch ID / service /
      change class / pattern / outcome
- [ ] `banks.recover_consolidation(bank_id)` then assert observations exist with proof counts >= 2
- [ ] Bank config: mission, 5 directives, disposition 4/5/2 — then `get_bank_config` and print it
- [ ] `api/app/lookalike.py`: `recall_precedents` with `query_timestamp`, deterministic `rank`, `MIN_PROOF`
- [ ] Flip-detail via 9Router **JSON mode** (`response_format: json_object`); never `tool_choice: "auto"`
- [ ] `no_precedent` path returns coverage % plus the two nearest declined precedents
- [ ] `api/app/ledger.py`: 4 flags, 3 ignored, 2 costed, promoted class feeds `rank(prefer=...)`
- [ ] `Assessment` contract frozen and served by `/api/assess` before any frontend code
- [ ] `replay.py` over all 40 launches, cached to `data/replay.json`; `/api/metrics` serves it
- [ ] `web/`: one screen, three presets, `MEMORY=on/off`, precedent cards with citations and trend badges,
      **flip detail as the hero card**, declined list, ledger, metrics row, prompt preview
- [ ] `api/tests/`: preset A returns a precedent, preset C returns `no_precedent`, ledger promotion changes
      preset A's top card, ground-truth totals match the corpus
- [ ] `web/` gate green: `tsc --noEmit`, lint, vitest, build (Playwright if a browser is installable)
- [ ] Push to `main`; Dokploy stack (`pre-mortem` project, `pre-mortem-Vikk` GitHub app) deploys automatically
- [ ] `compose.one | .createEnvFile` is `true`; env block written with a single newline-separated string
- [ ] Deployment polls to `done` (a 200 from `compose.deploy` is not success), then `curl /health` on the
      deployed API returns Hindsight reachable + `test_bank_llm` ok
- [ ] Deployed `POST /api/seed`, then `POST /api/consolidate`, then `smoke.py --url https://<api-domain>`
- [ ] **Freeze the real precision/coverage numbers** into `PLAN.md` and the README. Do not tune the write-up
      to match a target; tune `MIN_PROOF` or corpus density, then re-run

## Pre-record (30 min, do not skip)

- [ ] Fresh seed, then `recover_consolidation`, then confirm observations visible in the UI
- [ ] `test_bank_llm` passes
- [ ] All three presets exercised end to end, twice
- [ ] `data/replay.json` present so the metric charts render instantly
- [ ] Prompt preview renders without cutting off
- [ ] Containers restarted clean, browser cache cleared, zoom fixed, notifications silenced, other tabs closed
- [ ] No secrets on screen: check the browser devtools network tab and the `.env` is not open in an editor
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
- [ ] README: `docker compose up`, the 5-year-old explainer, a "How Hindsight is used" section naming
      `retain` / `recall(query_timestamp)` / `reflect(response_schema)` / observations with proof counts and
      freshness trends / `directives` / `disposition` / `recover_consolidation` / `preview_prompt` /
      `get_memories_timeseries`
- [ ] README states the stack honestly: self-hosted Hindsight (FOSS) driving 9Router, local embeddings
- [ ] Control Plane (`:9999`) works so judges can inspect banks directly
- [ ] Architecture diagram or the ASCII tree from `docs/ARCHITECTURE.md` in the README
- [ ] `.env.example` committed, `.env` untracked; `git status --porcelain` and `git log -p -- .env` clean
- [ ] `NEXT_PUBLIC_API_BASE_URL` passed as both build arg and runtime env in compose
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
