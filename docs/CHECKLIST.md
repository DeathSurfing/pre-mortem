# Checklist

Two days. Day 1 build, day 2 video + content. Tick in order.

The stack as it actually ships: **Hindsight Cloud** (no memory container), **Laya** baked into the api image
(no model-serving container), **OpenCode Go** for our own prose calls, **FastAPI + Next.js**. Two containers
total: `api` and `web`.

---

## Before anything (30 min): this block is a gate

- [ ] `.env` from `.env.example`. Needs: `HINDSIGHT_API_KEY` (hsk_...), `OPENCODE_GO_API_KEY` (oc_sk_...),
      `HINDSIGHT_BANK_ID=premortem` (legacy deploy bank), `HINDSIGHT_BIZ_BANK_ID=bizdecisions` (the bank the
      product reads), `NEXT_PUBLIC_API_BASE_URL`, and the `LAYA_*` vars (all have working defaults)
- [ ] **Verify the OpenCode Go key directly before blaming anything else.** Chat requires the
      `x-opencode-session` header; without it the call fails with `MissingSessionID`:
      ```bash
      curl -s -X POST https://opencode.ai/zen/go/v1/chat/completions \
        -H "Authorization: Bearer $OPENC..._KEY" -H 'content-type: application/json' \
        -H 'x-opencode-session: pre-mortem-local' \
        -d '{"model":"deepseek-v4.1-flash","stream":false,"messages":[{"role":"user","content":"say OK"}]}'
      ```
- [ ] **Verify the Hindsight key** with a free call (no LLM cost): `banks.list_banks` returns a list
- [ ] `banks.get_bank_config(bank_id)` is readable and shows disposition `skepticism 4 / literalism 5 / empathy 2`
- [ ] One `retain` then a `recall` returns facts with `metadata` intact (this is the seed's contract)
- [ ] **If any of this fails, stop.** Fallbacks in order: (1) a stronger OpenCode Go model for
      `LLM_MODEL`, (2) `HINDSIGHT_LLM_MODEL` swap, (3) the 9Router lane
      (`HINDSIGHT_API_LLM_PROVIDER=openai` + `_BASE_URL=$NINEROUTER_URL/v1`). Do not start app work on a
      broken memory layer

## Day 1: build

- [ ] `api/app/bizcorpus.py` sanity check (free, no API): **72 decisions across 10 domains**, 47 good /
      22 bad / 3 mixed outcomes, 25 materialised, 11 clean mirrors, derivable coverage ~0.6. Every
      materialised outcome must trace to a pattern
- [ ] `POST /api/biz/seed`: 72 retains, one extraction call each. Run deliberately, it costs tokens
- [ ] **Wait for observations.** They are a background job: `total_observations` is 0 right after retain
      and needs ~1-3 min. `POST /api/biz/consolidate` polls until they exist. Never seed right before
      recording
- [ ] Bank is fully populated: **77 documents / 68 observations / 276 nodes / 6802 links / 0 pending /
      5 directives** in `/api/biz/bank`
- [ ] `api/scripts/smoke.py` green against the deployed URL (42 checks on the business path)
- [ ] **All five presets verified end to end** (A through E, all of them `decision` mode):
      A pricing/discount -> **high** (0.79, cites D-2025-0002, D-2025-0013 bad, D-2025-0023 mirror),
      B hiring/senior-hire -> **high**,
      C expansion/new-office -> **no precedent**, refuses, then a labelled LOW-confidence guess,
      D compliance/audit-finding -> **high** (0.67, cites D-2026-0038 bad + D-2027-0062 mirror),
      E partnership/exclusivity-agreement -> **high** (0.67, cites D-2026-0045 bad + D-2027-0068 mirror)
- [ ] Every cited id cross-checked against the corpus (`engine.attribution_unverified` is empty)
- [ ] `citations_in_prose` non-empty and `uncited_facts` empty for A and B
- [ ] Ledger reads **5 flags / 4 ignored / 3 costed** and promotes `pricing@discount`,
      `hiring@senior-hire`, `marketing@budget-shift`
- [ ] **Mode routing verified**: `python3 api/scripts/mode_check.py <base url>` green. 9 messages, each
      asserting the mode contract (chat: no verdict, no cites; query: records retrieved, no verdict;
      decision: verdict present). Includes the action+history regression case
- [ ] **Follow-ups verified**: `python3 api/scripts/conversation_check.py <base url>` green. Opening
      question reviewed, three follow-ups all `chat` with `follow_up=true`, no verdict re-issued
- [ ] Reasoning trace streams: a full review emits `reasoning` SSE events before the `delta` events, and
      the UI renders them collapsed behind a disclosure rather than inline
- [ ] `web/` gate green: `npx tsc --noEmit` and `npx next build` both clean
- [ ] Confirm from the built CSS and served HTML: body font is **Inter**, headline font is **Newsreader**,
      paper is `rgb(250,249,245)`, accent is `#c2643f`. (There is no browser test in this repo: the UI is
      checked from built CSS, served HTML and the deployed bundle, never from rendered pixels. If fonts
      look like Times New Roman, see the trap below)
- [ ] Push to **`master`** (not `main`); Dokploy autoDeploys. Poll `deployment.allByCompose` to `done`. A
      200 from `compose.deploy` is queued, not success. Allow ~60s after a deploy before trusting a 404
- [ ] `curl https://premortem-api.lexcontra.com/health` -> `ok: true`, `bank_id: bizdecisions`, both banks
      readable. `laya.loaded: false` is the correct idle answer (lazy-loaded on first classify); `enabled: true`
      is what must hold. Readiness (`Hindsight` reachable, documents list) lives on `/health/deep` and is slow
- [ ] Run one live stream against the deployed API and confirm the event order:
      `status -> classify -> verdict -> precedents -> reasoning* -> delta* -> done`
- [ ] Send a follow-up against the deployed API with `POST /api/biz/redflag/stream` and a `history` array,
      and confirm it returns `chat` with no verdict

## Day 2: video + content

- [ ] Beats 0-5 recorded per `docs/DEMO.md`, beats 3 and 4 with a second take
- [ ] Shot 16 recorded: type an uncovered decision from scratch and let it return `No precedent`
- [ ] Subtitle burn-in (judges often watch muted)
- [ ] 3:00 cut assembled; 30-45s short cut assembled
- [ ] Article written per the outline in `docs/DEMO.md`, honesty section included
- [ ] Per-member social post, both variants considered, one posted each
- [ ] Video uploaded, link verified in an **incognito window** (private links are a classic submission killer)

## Submission

- [ ] Repo flipped from private to public
- [ ] README: setup, the 5-year-old explainer, the three modes, follow-ups, the reasoning trace, the
      "How Hindsight is used" table, the endpoint list, the Laya section
- [ ] `.env.example` committed; `.env` untracked. `git status --porcelain` and `git log -p -- .env` clean
- [ ] Demo video link in the README and in the submission form
- [ ] Live demo rehearsed twice against a fresh seed
- [ ] One paragraph stating exactly how Hindsight memory is used, per the submission requirement

## Pre-record (30 min, do not skip)

- [ ] Fresh seed, then `POST /api/biz/consolidate`, then confirm observations exist in `/api/biz/bank`
- [ ] All five presets exercised twice
- [ ] One greeting and one history question exercised, so the `chat` and `query` modes are on camera
- [ ] At least one follow-up exercised on camera
- [ ] Browser cache cleared, zoom fixed, notifications silenced, other tabs closed
- [ ] No secrets on screen: devtools network tab closed, `.env` not open in an editor
- [ ] Recording tool at 1080p, mic tested, 20 seconds of room tone captured for edits

## Honest-framing gates (any failure here costs the memory score)

- [ ] Every claim on screen carries a decision id, an evidence count, or a coverage number
- [ ] The LLM never produces the verdict. `rank.py` does, and the rule text says so in plain words
- [ ] `No precedent` is shown at least once on camera, with the guess panel visible and badged low confidence
- [ ] An unverified attribution, if one appears, is labelled rather than quietly quoted
- [ ] No sentence anywhere implies the tool decides, files, or approves anything
- [ ] Nothing on screen or in the README claims the UI was verified visually. It was checked from built CSS,
      served HTML and the deployed bundle

---

## Traps that cost real time (all hit, all fixed)

| Trap | Symptom | Fix |
|---|---|---|
| `--font-sans` computes empty | Every font renders as Times New Roman | Declare the family list literally, no `var()` chain. shadcn appends `@layer base { body, html { font-family: var(--font-sans) } }` which beats a plain `body` rule |
| shadcn `init` rewrites `globals.css` | Accent becomes near-white, tokens vanish | Re-apply `:root` and `@theme inline` after `init`. It also sets `--accent: oklch(0.97 0 0)` |
| Stale `next-server` serves old CSS | Computed styles contradict the built file | The process is named `next-server`, so `pkill -f "next start"` does not match. Match on `/proc/<pid>/cwd` instead |
| OpenCode Go `reasoning_content` | User watches the model think | Reasoning deltas arrive BEFORE content. Unpack the stream as `async for kind, piece in chat_stream(...)`, emit reasoning as its own `reasoning` SSE event, and only `content` as `delta` |
| Small `max_tokens` on a reasoning model | Empty `content`, or reasoning text leaked as the answer | Use `max_tokens >= 3000` for user-visible generation |
| A decision classified as `chat` | The whole review is silently withheld, and nothing looks broken | Treat the two errors as asymmetric: keep the Laya-decides-alone band tiny (`>= 0.60` decision, `<= 0.15` chat), let the model arbitrate the middle, and run `mode_check.py` after any prompt change |
| A follow-up reviewed from scratch | "what if we cap it at 15 percent?" loses the thread and re-issues a verdict | Any message with prior history is always `chat`. `conversation_check.py` asserts it |
| Consolidated observations have empty `metadata` | Every evidence count reads 1, no trends render | Parse attributes from the observation text; cross-check every id against the corpus before quoting it |
| Ledger double-counts | 4 flags reported as 20 | Hindsight extracts several facts per document. Keep only `world`, dedupe by decision id, use a deterministic `document_id` |
| Observations not ready | `total_observations: 0` at demo time | They are a background job. `recover_consolidation` + poll, or the trend badges are empty |
| `/health` calling a third-party API | Container marked unhealthy under latency, Traefik withdraws the route, every URL on the API host returns a plain-text `404 page not found` while the app runs fine | `/health` answers from local state only and is the healthcheck; the networked checks live on `/health/deep`. A third-party API must never be able to unroute the deployment |
| 9Router `gareebi` fallback | `Model is unavailable` under load, doubling latency | `LLM_FALLBACK_MODEL` is deliberately empty in compose |
| python-urllib default UA | Cloudflare 403 on the deployed API while curl returns 200 | `smoke.py` sends a real User-Agent |
