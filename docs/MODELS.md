# Model & deployment plan

Locked decisions. Everything marked VERIFIED was produced by running the command; anything else is marked
UNVERIFIED with a fallback. Supersedes the earlier 9Router-first version.

**Read sections 10-15 first if you want what the running system actually does.** Sections 1-9 are the
build-time plan and the live-probe record, and they are kept as written. Sections 10+ document the parts
added after: the reasoning lane, the three-mode router, the `COVERED_DOMAINS` rule, Laya's deployment shape,
where the verdict is computed, and the prompt store. Where a plan section has been overtaken by events it
now says so inline.

## 1. LLM: OpenCode Go (primary), 9Router (fallback, disabled)

OpenCode Go is OpenAI-compatible at `https://opencode.ai/zen/go/v1`. Hindsight also ships a **native
`opencode-go` provider**, so this is one provider for both our app and Hindsight's own extraction calls.

### VERIFIED behaviour

| Check | Result |
|---|---|
| `GET /v1/models` | 35 models: `deepseek-v4-flash`, `deepseek-v4.1-flash`, `deepseek-v4-pro`, `glm-5.1/5.2/5.3`, `glm-5.3-flash`, `kimi-k2.6`, `kimi-k2.7-code`, `kimi-k3`, `minimax-m2.5/2.7/m3`, `qwen3.6-plus`, `qwen3.7-max/plus`, `qwen3.8-max`, `qwen3.8-flash`, `grok-4.6/4.7`, `gpt-5.6-luna`, `gpt-6-luna`, `mimo-*`, `longcat-*`, `space-bunny-free`, `omen-alpha`, `hy3`, `hy4-preview` |
| `/v1/models` without the session header | works, returns the list |
| `/v1/chat/completions` without the session header | **`MissingSessionID`: "Request is missing x-opencode-session and cannot be routed efficiently."** So the header is required on chat, not just advisory |
| `/v1/chat/completions` **without** the session header | `MissingSessionID` — hard failure, not a warning |
| `/v1/chat/completions` with `x-opencode-session` | **works.** `deepseek-v4-flash` returned `OK` |
| Tool calling, `tool_choice: "auto"` | **WORKS** (`pick_fix` called with correct args). Better than 9Router, which silently ignores auto |
| Tool calling, forced named function | works on `deepseek-v4-flash` and `deepseek-v4.1-flash` |
| `response_format: {"type":"json_object"}` | works on both models, returns valid JSON |
| Multi-turn tool loop (assistant `tool_calls` -> `role:"tool"` result -> continue) | works; the model re-issues `recall` rather than jumping to `done`, so loop depth must be capped |
| Reasoning output | `deepseek-v4-flash` returns a `reasoning_content` field alongside `content`. This is a real reasoning trace, not noise: it is streamed to the UI collapsed behind a disclosure. See section 10 |
| Hindsight native provider | `HINDSIGHT_API_LLM_PROVIDER=opencode-go`, default base URL `https://opencode.ai/zen/go/v1`, name the model via `HINDSIGHT_API_LLM_MODEL` |

**Status: VERIFIED WORKING.** The Go key is live and the Dokploy env block holds it. Measured behaviour on
`deepseek-v4-flash`: chat, forced tools, **auto** tools, JSON mode, and multi-turn tool loops all work.
This means Hindsight's `reflect` (which drives forced tool calling internally) is expected to work, and the
app can use plain JSON mode without a forced-tool fallback.

Remaining unverified item is Hindsight itself (the container could not be started here: Docker CLI present,
no daemon). One `reflect` with `response_schema` via `api/scripts/smoke.py` on Dokploy closes it.

### Non-negotiable rules for this provider

1. **Always send `x-opencode-session` on chat calls.** One stable string per run (`pre-mortem-prod`), reused.
   Without it the call fails outright, it does not silently degrade. For Hindsight's own calls this is set via
   `HINDSIGHT_API_LLM_EXTRA_HEADERS={"x-opencode-session": "pre-mortem-prod"}` in case the native
   `opencode-go` provider does not send it itself.
2. **`gpt-6-luna`, `gpt-5.6-luna`, `qwen3.8-max` are the likely choices for extraction quality.** Start with
   `deepseek-v4-flash` (cheap, fast, likely enough for fact extraction), move up only if extraction is noisy.
   Hindsight makes one extraction call per retain, so 40 launches = 40 calls.
3. **`HINDSIGHT_API_LLM_EXTRA_HEADERS` is set in the Dokploy env** to belt-and-braces the session header.
   If Hindsight's `opencode-go` provider already sends one, a duplicate header is the only risk; if the request
   then fails, drop this var. Test both ways in the smoke script.
4. **Embeddings** are served by Hindsight Cloud. OpenCode Go exposes no `/v1/embeddings` route; the
   self-host plan was to run a local model, and that is moot now that Hindsight is Cloud.
5. Keep `HINDSIGHT_API_LLM_TIMEOUT=180`; combo/reasoning models are slower than a small chat model.
6. **Do not set a fallback model.** `LLM_FALLBACK_MODEL` ships blank on purpose: the 9Router lane returned
   "Model is unavailable" under load, and a dead fallback doubles latency on every call. Measured behaviour
   is kept below for the record, but nothing is wired to it.

### 9Router as fallback (VERIFIED working, deliberately NOT wired)

Kept for the record because the probe results were real. The lane is disabled in `docker-compose.yml`:
`LLM_FALLBACK_MODEL` defaults to empty. Do not re-enable it without measuring the latency cost.

| Check | Result |
|---|---|
| `gareebi`, `ocg/deepseek-v4.1-flash` | chat works |
| `kimchi/deepseek-v4.1-flash` | **402, provider out of credits** |
| any `openrouter/*` model or embedding | **403, key limit exceeded** |
| `tool_choice: "auto"` | **not honoured**, returns prose with no `tool_calls` and no error |
| forced `tool_choice` (named function) | works on both models |
| `response_format: {"type":"json_object"}` | works on both models |
| under load | **"Model is unavailable"**; that is what caused the disable |

### If OpenCode Go blocks us on build day

1. OpenCode Go with a working subscription (the live path).
2. Laya carries the classification and routing locally, so the app still runs without an LLM for those.
3. 9Router `gareebi`, only after re-measuring the load behaviour above.

## 2. Hindsight: Vectorize Cloud (self-host plan abandoned)

**This section is the original plan and was overtaken by events. What shipped is Vectorize Cloud.**

The original reasoning was: Cloud pins the extraction provider, so it cannot use OpenCode Go, and changing it
needs `buy_credits` plus a support ticket; self-hosting would give one provider for the whole system. In the
end the service runs on Cloud (`HINDSIGHT_API_URL` defaults to `https://api.hindsight.vectorize.io`) and the
API 0.10.1 probe results in section 9 were all measured against it. There is no `hindsight` container in the
stack, so the compose below is not what deployed.

Consequences that actually matter and are all handled:

- `test_bank_llm` is unavailable on Cloud (9.2), so it cannot be the health probe.
- `GET /health` must not fan out to Hindsight, or a third-party API can unroute the deployment. Liveness is
  answered from local state only; reachability moved to `/health/deep`. See the fact sheet's health section.
- Embeddings are served by Hindsight Cloud; the app makes no embedding calls of its own.

```yaml
# ORIGINAL PLAN, not deployed. Kept for the reasoning, not as a description of the running stack.
environment:
  HINDSIGHT_API_LLM_PROVIDER: opencode-go          # native provider
  HINDSIGHT_API_LLM_MODEL: ${HINDSIGHT_LLM_MODEL:-deepseek-v4-flash}
  HINDSIGHT_API_LLM_API_KEY: ${OPENCODE_GO_API_KEY}
  HINDSIGHT_API_LLM_TIMEOUT: "180"
  HINDSIGHT_API_LLM_MAX_RETRIES: "3"
  HINDSIGHT_API_EMBEDDINGS_PROVIDER: local
  HINDSIGHT_API_EMBEDDINGS_LOCAL_MODEL: BAAI/bge-small-en-v1.5
```

### UNVERIFIED, and how to close it (CLOSED)

An actual retain -> recall -> reflect round trip. Docker CLI exists in the agent container but **no daemon**
(`/var/run/docker.sock` absent), so it cannot be tested here. **Closed:** section 9.8 records the live run
against Cloud, and `api/scripts/smoke.py` runs against a deployed URL: `reflect` returns a cited answer.

`reflect` was the risky call: Hindsight's reflect agent uses forced tool calling internally, so a provider
that ignores forced tools breaks reflect (not retain).

## 3. Dokploy target (discovered, live)

Stack already created and configured. Verified state:

| Thing | Value |
|---|---|
| Project | `pre-mortem` — `projectId ShLB1aaWQmQw0b0ipoRuu` |
| Environment | `production` — `environmentId 616zDbsDYbuty50FIDNd8` |
| Compose stack | **`pre-mortem` — `composeId hQJmXPzH4h31K6PNN9M5_`** |
| Generated app name / container prefix | `pre-mortem-vikk-qrxsdn` (do not rename; Traefik labels and volumes key on it) |
| Source | `sourceType=github`, `repository=pre-mortem`, `owner=DeathSurfing`, `branch=master`, `composePath=./docker-compose.yml`, `autoDeploy=true`, `triggerType=push` |
| GitHub provider | `pre-mortem-Vikk` — **`githubId 6VcRqgkdq8MKEgPihfQBi`** (`gitProviderId JUtqJNu2wLKSXdMS-xuS3`) |
| Provider scope | `DeathSurfing/pre-mortem` only. Correct |
| `createEnvFile` | `true` (required: our compose interpolates `${VAR}`) |
| `hasGitProviderAccess` | `true`, `unauthorizedProvider` unset -> pushes will deploy |
| Domains | `premortem.lexcontra.com` -> service `web` :3000, `premortem-api.lexcontra.com` -> service `api` :8000, both https + letsencrypt |
| Env keys stored | `OPENCODE_GO_API_KEY` (live, 51 chars), `OPENCODE_GO_BASE_URL`, `OPENCODE_SESSION`, `LLM_MODEL=deepseek-v4.1-flash`, `HINDSIGHT_LLM_MODEL=deepseek-v4-flash`, `HINDSIGHT_LLM_EXTRA_HEADERS`, `NINEROUTER_URL`, `LLM_FALLBACK_MODEL=gareebi`, `HINDSIGHT_BANK_ID=premortem`, `NEXT_PUBLIC_API_BASE_URL`, `MIN_PROOF=1` |
| Status | **Deployed and live.** `https://premortem.lexcontra.com` (web :3000), `https://premortem-api.lexcontra.com` (api :8000). After a deploy, allow ~60s before trusting a 404: the container restarts and Traefik re-binds its route |

**Trap already hit, worth remembering:** `compose.update`'s `githubId` field is **not** the
`gitProviderId`. `github.githubProviders` returns both, and only the second column works:

| provider name | `githubId` (this one) | `gitProviderId` (NOT this) |
|---|---|---|
| LexContra | `X7eOyUnuSKsyZg48ak2VQ` | `ByaCPo88c8uwhlRjx3GoZ` |
| pre-mortem-Vikk | `6VcRqgkdq8MKEgPihfQBi` | `JUtqJNu2wLKSXdMS-xuS3` |

Passing `gitProviderId` fails with a raw Postgres error (`Failed query: update "compose" ... params: ...`)
and sets the column to NULL. Also: `compose.update` rejects `owner`/`repository` when `githubId` is
unset, so set the repo fields first, then `githubId`, then `composeFile`.

Remaining blocker: **DNS**, now **closed**. `premortem.lexcontra.com` and `premortem-api.lexcontra.com`
both resolve and serve over https, so the Let's Encrypt challenge succeeded and the stack is live.

## 4. Stack shape on Dokploy

One compose stack (`composeType: docker-compose`, `sourceType: github`, repo `DeathSurfing/pre-mortem`,
branch `master`, `autoDeploy: true`, `triggerType: push`) with **two** services. Hindsight runs on Vectorize
Cloud, so there is no memory container; Laya is baked into the api image at build time, so there is no
model-serving container either.

| Service | Image / build | Port | Public |
|---|---|---|---|
| `api` | `./api` Dockerfile | 8000 | yes, `premortem-api.lexcontra.com` |
| `web` | `./web` Dockerfile | 3000 | yes, `premortem.lexcontra.com` |

```text
browser ──▶ web :3000 ──▶ api :8000 ──▶ api.hindsight.vectorize.io
                                    └──▶ opencode.ai/zen/go/v1
                                    └──▶ Laya ONNX int4, in-process
```

Rules:
- Both `web` and `api` get a public domain (the demo URL pattern needs the api reachable by the browser).
- `NEXT_PUBLIC_API_BASE_URL` is a **build arg** (Next inlines it) and must also be present as a runtime
  `environment` entry. Set both.
- `api`'s healthcheck points at `/health`, which is local-state only, and gets `start_period: 90s` because the
  first Laya load builds the ONNX session. Do not point it at `/health/deep`.

## 5. Dokploy wiring gotchas that will bite on deploy day

From experience with these stacks, verify each of these rather than discovering them on camera:

1. **`createEnvFile` must be `true`.** Our compose file uses `${VAR}` interpolation. Dokploy's
   `saveEnvironment` replaces the whole env block, and if `createEnvFile` is false the generated
   `docker compose` command runs without `--env-file .env`, so interpolation fails with
   *"required variable ... is missing a value"* and one-shot/dependent services never start. Confirm with
   `compose.one | .createEnvFile` and set it via `compose.update`.
2. **`saveEnvironment` replaces everything.** Read `compose.one` → `.env`, append, write back as one
   newline-separated string. Writing a single var deletes the rest.
3. **A Dokploy deploy is asynchronous.** A 200 from `compose.deploy` means queued, not up. Poll
   `deployment.allByCompose` until the newest entry is `done`, then curl the app independently.
4. **CI never builds the Docker image for a Dokploy stack.** So Dockerfile defects (missing runtime deps,
   wrong start command, wrong `EXPOSE`) pass CI green and only fail at deploy. Assert the critical commands
   at build time in the Dockerfile (`RUN python -c "import fastapi, hindsight_client"`, `RUN node -e "require('./next.config')"` or equivalent) so the failure lands in the build step, not the deploy.
5. **Next.js**: do not enable `output: "standalone"` and then run `next start` — standalone needs
   `node .next/standalone/server.js` plus a manual copy of `.next/static`. Pick one path and match the
   Dockerfile's CMD to it.
6. **`next build` must not require runtime secrets.** Collecting page data imports every module a route
   touches; throwing on a missing env var breaks the build. Read env lazily and expose problems through
   `/api/health`.
7. **The FastAPI service must bind `0.0.0.0`**, not `127.0.0.1`, or Traefik cannot reach it.
8. **Health checks**: give `api` a real `HEALTHCHECK` against `/health`. That endpoint must be **liveness
   only** and answer from local state. Pointing it at a check that touches Hindsight is what caused a real
   outage: under latency the container was marked unhealthy, Traefik withdrew its route, and every URL on the
   API host returned Traefik's plain-text `404 page not found` while the app was running fine. A third-party
   API must never be able to unroute the deployment. Reachability lives on `/health/deep`.

## 6. Deployment sequence (once the key and code exist)

1. `git push` to `master` (the branch is `master`, not `main`); confirm the Dokploy stack's `autoDeploy`
   fires, or call `compose.deploy`.
2. Watch `deployment.allByCompose` until `done`; on failure read `deployment.readLogs`. Then allow ~60s
   before trusting a 404: the container restarts and Traefik re-binds its route.
3. `curl https://premortem.lexcontra.com/` -> the UI loads.
4. `curl https://premortem-api.lexcontra.com/health` -> liveness from local state: config, bank ids, model
   names, Laya status. Then `curl .../health/deep` -> Hindsight reachable, bank readable, directives,
   document list. Laya may legitimately report `loaded: false` until the first classify.
5. `POST /api/biz/seed` once, then `POST /api/biz/consolidate`, then confirm observations have proof counts.
6. `python3 api/scripts/smoke.py https://premortem-api.lexcontra.com` as the pre-record gate. `--deep` adds
   more checks. `api/scripts/mode_check.py` and `api/scripts/conversation_check.py` cover the router.
7. Only then record. Re-run steps 4-6 the morning of recording.

## 7. Env keys

```bash
# primary LLM
OPENCODE_GO_API_KEY=            # new key, Go subscription active
HINDSIGHT_LLM_MODEL=deepseek-v4-flash
LLM_MODEL=deepseek-v4.1-flash   # our app: flip detail + prose
OPENCODE_GO_BASE_URL=https://opencode.ai/zen/go/v1
OPENCODE_SESSION=pre-mortem-prod   # stable x-opencode-session value

# fallback LLM
# deliberately empty: the 9Router lane returned "Model is unavailable" under load, and a dead fallback
# doubles latency on every call.
LLM_FALLBACK_MODEL=
NINEROUTER_URL=https://9router.lexcontra.com

# hindsight (Cloud)
HINDSIGHT_API_URL=https://api.hindsight.vectorize.io
HINDSIGHT_API_KEY=
HINDSIGHT_BANK_ID=bizdecisions        # /health reports `bank_id: bizdecisions`
HINDSIGHT_BIZ_BANK_ID=bizdecisions    # code default; banks: {business: bizdecisions, legacy_deploy: premortem}

# Laya: local classifier, weights baked into the api image
LAYA_ENABLED=1
LAYA_REPO=techtheist/laya-onnx
LAYA_SUBFOLDER=en
LAYA_ONNX_FILE=model_int4.onnx

# web <-> api
NEXT_PUBLIC_API_BASE_URL=https://premortem-api.lexcontra.com

# ranking
MIN_PROOF=1
```

On this agent box the same OpenCode Go key currently lives as `OPENCODE_GO_API_KEY` in `/opt/data/.env`.
Never commit either key; `.env` is gitignored and `.env.example` is tracked.

## 8. Cost notes

- Hindsight runs on Vectorize Cloud, so extraction (`retain`) and `reflect` do consume credits. Section 9.6
  has the measured per-operation token counts.
- OpenCode Go: one subscription, model list is generous. Prefer `deepseek-v4-flash` for the seed (one
  extraction call per document) and reserve a stronger model for the review prose if quality needs it.
- Seed once and keep it. Re-seeding costs extraction calls plus consolidation, not free.
- Laya is free at the margin: local, in-process, no per-call cost. Predict is 1.4-3.0s and peak RSS 996MB.

## 9. VERIFIED corrections from live probing (API 0.10.1, Hindsight Cloud)

These were measured against the real API on 2026-09-27 and **invalidate parts of the original plan**.
Recorded here so the code never repeats them.

### 9.1 `query_timestamp` does NOT filter results — the no-lookahead claim was WRONG

| Query | Results |
|---|---|
| `recall(query="pool change", query_timestamp=None)` | 7 results, `occurred_start` in {2025-11-01, 2026-03-14} |
| `recall(..., query_timestamp="2026-03-13")` (day before the fact) | **7 results, same set** |
| `recall(..., query_timestamp="2024-01-01")` (before everything) | **7 results, same set** |

It is a ranking/temporal-reasoning hint, not a filter. `tags` and `min_scores` also do not hard-filter
(recall with `tags=["pattern:P1"]` on untagged memories returned everything). `tag_groups` behaves the same.

**Consequence:** if the whole corpus is ingested at once, the agent can retrieve facts from launches that
had not happened yet at the point being evaluated. Any claim of "lookahead bias is structurally impossible"
would have been false.

**Replacement mechanisms, both honest:**
1. **Staged ingestion** (the demo does this): seed only up to day N, ask, then ingest more and ask again.
   The agent literally cannot know what is not yet in the bank. This is server-enforced truth, not a hint.
2. **Offline replay with Python-side ordering**: for each launch i, take the recall result set and keep only
   memories whose `occurred_start` precedes launch i's timestamp. Deterministic, free, verifiable, and stated
   in the README as our own evaluation logic rather than a server guarantee.

### 9.2 `test_bank_llm` is unavailable on Cloud

`banks.test_bank_llm` returns 404, and `get_version().features.bank_llm_health` is `False`. Guard it:
call it only if the feature flag is true, otherwise substitute a 1-token `reflect` as the health check.

### 9.3 `create_or_update_bank` works, but the client wrapper is async

Verified: `banks.create_or_update_bank` and `banks.get_bank_config` are **async** on the `banks` namespace
(`inspect.iscoroutinefunction` -> True), while `retain` / `recall` / `reflect` are sync wrappers over async.

**Trap that cost a probe run:** the client's internal `_run_async` calls `asyncio.get_event_loop()`, so
calling `asyncio.run()` per call closes the loop the client later depends on. Every subsequent call then
fails with `RuntimeError: Event loop is closed`. Fix: create ONE event loop, `asyncio.set_event_loop(loop)`
at import, and use `loop.run_until_complete(...)` for the async namespace methods. Under FastAPI, call the
async methods with `await` inside the request handler instead; never wrap them in `asyncio.run`.

### 9.4 Config that landed correctly

`get_bank_config` returns `{bank_id, config, overrides}`. Confirmed values after `create_or_update_bank`:
`disposition_skepticism=4`, `disposition_literalism=5`, `disposition_empathy=2`, `enable_observations=True`,
`enable_graph_retrieval=True`, `enable_temporal_retrieval=True`, `enable_reranking=True`,
`retain_custom_instructions` preserved, `consolidation_llm_batch_size=8`.

Note `retain_extraction_mode: concise` is the default. For this project set it to a fuller mode if
extraction turns out to drop the fix text; the probe's extraction was good enough as-is.

### 9.5 Extracted facts, measured

One retain of a single launch document produced **4 `world` facts** with `metadata` preserved verbatim
(`launch_id`, `service`, `change_class`, `pattern_id`, `outcome`) and date-aware `occurred_start` per fact,
including a correct 2025-11-01 date for a *referenced* prior launch. Consolidation was pending
(`pending_consolidation: 4`) until forced.

### 9.6 Cost per operation (credit discipline)

One retain of a ~1 KB launch doc: **`input_tokens=2253, output_tokens=903, total_tokens=3156`**.

Consequences for a $55 budget:
- **`recall` uses no LLM** (retrieval only) -> effectively free. Make it the default path.
- **`retain` and `reflect` cost LLM tokens.** Seed is ~40 x 3.2k = ~126k tokens, plus consolidation.
- **`reflect` is the expensive call** (agentic loop, up to 10 iterations). Budget 1-2 showcase calls only.
- **Design decision:** the replay and the demo presets use `recall` (free) + our own OpenCode Go model for
  the prose (`LLM_MODEL=deepseek-v4.1-flash`, one flat subscription). `reflect` is demonstrated once, on
  camera, as the "Hindsight answered it itself" beat. This is both cheaper and more auditable, since the
  metric then does not depend on an LLM at all.

### 9.7 Bank hygiene

`documents.list_documents(bank_id)` and `documents.delete_document(bank_id, doc_id)` exist, so a re-seed can
clean up properly rather than leaving stale documents. `directives.list_directives(bank_id)` returns
`{items, total, limit, offset}` and worked (empty list). `memories` and `tags` are **not** client namespaces
on this version; use `list_memories`, `entities`, `documents`, `mental_models`, `operations`.

### 9.8 Run results (measured, API 0.10.1)

| Item | Measured |
|---|---|
| Deploy corpus | 40 launches retained in one batch; **157 nodes**, 42 documents |
| Business corpus | **72 decisions**, 10 domains, 5 prompts (A-E) |
| Business bank `bizdecisions` | **77 documents, 68 observations, 276 nodes, 6802 links, 0 pending, 5 directives** |
| Legacy deploy bank `premortem` | 42 documents (the abandoned deploy corpus, still served by the legacy endpoints) |
| Fact extraction rate | ~2.6 `world` facts per launch document |
| Observations after consolidation | **43** in the deploy run (needs wall-clock time: 178s in the run that passed); 68 live now |
| Directives created | 5, via `acreate_directive` (separate resource, not a bank field) |
| Disposition on the bank | skepticism 4, literalism 5, empathy 2 (confirmed via `get_bank_config`) |
| Calibration ledger | **5 flags raised / 4 ignored anyway / 3 cost something** |
| Promoted classes | `pricing@discount`, `hiring@senior-hire`, `marketing@budget-shift` |
| Replay coverage | found 7/12 materialised, derivable 7/12, **gap 0** |
| `reflect` through the API | works, returns a cited answer |
| Test suite | **34/34 checks pass** (`api/tests/test_e2e.py --seed --reflect`) |

**Two operational facts worth remembering:**
1. **Observations are a background job.** Immediately after retain, `total_observations` is 0 with
   `pending_consolidation` non-zero. `recover_consolidation()` nudges it, then it still needs minutes.
   `hindsight.wait_for_observations()` polls free `agent_stats` calls until they appear (178s observed).
   Never seed right before recording without waiting.
2. **Hindsight extracts several facts per document.** One launch produced ~2.6 facts, so recall returns
   the same `launch_id` repeatedly. `rank()` must dedupe by `launch_id` or the precedent list shows the
   same launch three times.

### 9.9 Corpus design rule learned from the first failed run

A "pattern break" must actually materialise, or the pattern is noise the agent cannot learn. In the first
corpus, 3 of 6 P1 breaks came out `clean` because outcome was chosen by `idx % 4`, so the agent was
penalised for a pattern the data did not contain. Fix: per-pattern outcome sequences (`_BREAK_PLAN` in
`corpus.py`), with most breaks materially breaking and exactly two staying clean so precision is a real
question rather than a guaranteed 100%. Plain (non-pattern) launches are now always clean, so every
materialised outcome traces to a pattern.

### 9.10 OpenCode Go: reasoning-token gotcha (measured)

`deepseek-v4.1-flash` is a reasoning model. With a small `max_tokens` the entire budget is spent on
`reasoning_content` and `content` comes back **empty** (or, worse, the reasoning text itself lands in
`content` where a user can see it). Measured on the same prompt:

| model | max_tokens | content | reasoning_content | completion tokens |
|---|---|---|---|---|
| `deepseek-v4.1-flash` | 900 | **reasoning text** (leaked) | — | — |
| `deepseek-v4.1-flash` | 3000 | clean answer | 0 chars | 117 |
| `deepseek-flash` | 900 | clean answer | 2248 chars | 591 |
| `deepseek-v4-flash` | 900 | clean answer | 345 chars | 182 |

**Rules:**
1. Use `max_tokens >= 3000` for any user-visible generation. Small budgets on a reasoning model are a
   correctness bug, not a cost saving.
2. **Keep `content` and `reasoning_content` in separate lanes.** Non-streaming `chat()` reads `content` and
   falls back to `reasoning_content` only if `content` is empty, so a tight budget degrades instead of
   erroring. Streaming `chat_stream(..., reasoning=True)` yields both and the caller unpacks; see section 10.
3. `deepseek-v4-flash` and `deepseek-flash` spend far fewer reasoning tokens, so they are the cheaper
   choice when latency matters more than prose quality.

### 9.11 Observations: empty metadata, and a provenance caveat

Consolidated `observation` memories come back with **empty `metadata`** (verified: `metadata: {}`), so
launch attributes must be recovered from their text, which states them plainly
("Launch L-2026-0034 for payments-service on 2026-04-21 involved a configuration change...").

Two consequences, both handled:

1. `rank.recover_attrs()` parses the launch id, service and change class from the text, with a synonym
   map, because observations describe changes in prose ("a configuration change", "a library upgrade")
   rather than with our class slugs. Without the synonym map every observation is dropped by the strict
   service+change-class filter, which is what silently made every proof count 1 and no trend badge
   renderable.
2. Observations are weighted as stronger evidence than a single raw fact (`TYPE_WEIGHT`), since
   consolidation only produces one when several launches share the shape. The UI labels them
   **"consolidated"** versus **"raw"** so a reader can tell a standing belief from one record.

**Caveat, stated rather than hidden:** consolidation can attach a launch id loosely. One observation
described a payments-service pool change while citing `L-2026-0034`, which in the corpus is an
auth-service launch. So an observation's id is a *hint*, not a citation-grade reference. Raw `world`
facts always carry exact metadata and are the citation-grade source; the UI shows the type for exactly
this reason. Do not quote an observation's launch id on camera as the precedent, quote the raw fact.

## 10. The reasoning lane (NEW)

OpenCode Go emits `reasoning_content` deltas **before** `content` on the SSE stream. Those deltas used to be
discarded; they are now a first-class lane.

`llm.chat_stream()` is an async generator of `(kind, text)` pairs, where `kind` is `"content"` or
`"reasoning"`. Callers **must** unpack the pair:

```python
async for kind, piece in llm.chat_stream(system, user, reasoning=True):
    ...
```

Tuple-shaped rather than two separate generators, so one upstream stream feeds both lanes in order. Passing
`reasoning=True` yields the `("reasoning", text)` pairs as well.

- Streamed to the UI as a `reasoning` SSE event, rendered collapsed behind a disclosure
  (`web/components/reasoning.tsx`), so it never competes with the answer.
- Measured volume: **2126-7027 chars** on a full discount review, **58-200** on a greeting. It scales with
  the question, which is a usable signal that the model is actually working.

The reason to surface rather than discard: these tokens are already paid for, and a review that shows its
working is easier to trust than one that does not. But they are collapsed by default, because the answer is
the product and the trace is the apparatus.

## 11. The three-mode router

Every incoming message is routed into one of three modes before anything else happens. This is the core
interaction model, and it is decided by **Laya's `domain_probability`**, which costs nothing.

| Mode | Trigger | Behaviour |
|---|---|---|
| `decision` | proposes an action to judge ("should we...", "I want to...") | full review: verdict, precedents, difference, guardrail, open questions |
| `query` | a question about the company's own history | recalls the records unfiltered, answers from them with cited ids, no verdict |
| `chat` | greetings, thanks, questions about the tool, follow-ups | conversational reply, no recall, no verdict, no citations |

Gate thresholds, constants in `api/app/bizlookalike.py`:

- `LAYA_MODE_DECISION = 0.60`: at or above, a decision
- `LAYA_MODE_CHAT = 0.15`: at or below, chat/query
- Between the bands the LLM arbitrates, and the decision is recorded on the classify result as
  `mode_arbitration` so it can be audited later.

Measured probabilities (production, live):

| Message | Mode | p |
|---|---|---|
| "hey, how are you doing today?" | `chat` | 0.2923 |
| "thanks, that helps" | `chat` | 0.214 |
| "what did we decide about the Acme renewal?" | `query` | 0.265 |
| "Should I give Acme a 30 percent discount to close the renewal this quarter?" | `decision` | 0.9883 |
| "We are considering opening an office in Lisbon." | `decision` | 0.9422 |

The band where Laya decides alone is kept deliberately tiny. The asymmetry that drives that choice: a
message that should have been reviewed but is answered conversationally silently withholds the entire
product, whereas a conversational message that gets reviewed is merely noisy. When in doubt, review.

### 11.1 Tie-break: action + history question is a `decision`

A message that **both** proposes an action and asks about the past is a `decision`, not a `query`. A review
cites the records anyway and additionally gives the judgement; `query` would withhold it.

**This was a real regression.** Adding query mode silently degraded preset E
("a partner is asking for exclusivity... I want to sign it quickly... What has burned us on deals like this
before?") from a `decision` into a `query`, because it reads as a history question. It is a `decision`.

`api/scripts/mode_check.py` routes 9 messages and asserts the mode contract for each, including this case:
`chat` gets no verdict and no cites, `query` retrieves records but issues no verdict, `decision` produces a
verdict.

### 11.2 Follow-ups are always `chat`

A message sent with prior conversation is **always** `chat`, whatever it reads like in isolation, and the
prior turns are passed to the model. Otherwise "what if we cap it at 15 percent?" would be classified as a
fresh decision and reviewed from scratch, losing the thread.

- Transport: `POST /api/biz/redflag/stream` with `{"prompt": str, "history": [{"role","content"}]}`. POST
  because history does not fit in a query string. The GET variant still works and takes `?prompt=` / `?preset=`.
- History is capped at 12 turns client-side.
- Answered with `FOLLOWUP_SYSTEM`, which permits citing only ids already present in the earlier answer and
  forbids a fresh risk rating.
- The frontend carries precedents forward from the most recent turn that had them, so ids in follow-up prose
  still render as pills.

## 12. `COVERED_DOMAINS` and the domain override rule

Laya has a fixed taxonomy with no bucket for **compliance, security or partnership**, and on those prompts it
returns its nearest label with high confidence. A numeric trust threshold cannot separate that from a genuine
conviction, because Laya is genuinely convinced.

So the LLM's domain wins whenever it names a domain the corpus actually covers. `COVERED_DOMAINS` is derived
from the corpus (`frozenset(d.domain for d in bizcorpus.corpus())`), not hand-listed, so it cannot drift from
the data.

**Measured consequence of getting this wrong:** an audit question classified as `launch` at **0.825
confidence** and cited launch decisions. High confidence on a wrong label is the failure mode, which is why
the rule is structural rather than threshold-based.

Laya's label is still reported, it is just not authoritative. Its value in this app is the calibrated
probability plus the reversibility and value-given-away signals.

## 13. Laya: deployment shape and measured performance

ONNX int4 build of `techtheist/laya-onnx`, 275MB, Apache-2.0. Bake into the api image at build time, so
there is no model-serving container.

| Metric | Measured |
|---|---|
| `LOAD` | 9.1s (first call only) |
| `PREDICT` | 1.4-3.0s |
| Peak RSS | 996MB |
| Hard dependencies | `torch 2.14.0+cpu` (via `laya/common.py`), `libgomp1` (torch CPU kernels) |

**Lazy-loaded on purpose.** The ONNX session is built on first classify, not at boot, so `/health` reports
`loaded: false` until the first use; `enabled: true` is the honest idle answer. The compose healthcheck gets
`start_period: 90s` for exactly this reason. A 996MB peak fits the 4GB cgroup.

Signals Laya contributes: `domain_probability`, `reversibility_label`, `gives_value_without_commitment`,
`is_high_blast_radius`. It is the router and the signal provider, **not** the decision-maker.

## 14. Where the verdict comes from

`rank.verdict()` in `api/app/rank.py` computes the risk. The model only writes the sentences.

It spans **both** outcome vocabularies, because the two corpora spell the same idea differently:

- deploy corpus: `incident`, `degraded` (fine = `clean`)
- business corpus: `bad`, `mixed` (fine = `good`)

`BAD_OUTCOMES = {incident, degraded, bad, mixed}` and `GOOD_OUTCOMES = {clean, good}`. A precedent with no
recorded outcome counts as neither, so it can support but never inflate risk.

Two rules that are easy to get wrong and were:

1. **"Precedents exist but none records a failure" is `medium`, not `low`.** No recorded failure is not
   evidence of safety.
2. **`outcome: None` renders `OUTCOME NOT RECORDED`, never "clean".** Absence is displayed as absence.

Confidence is `min(0.95, 0.35 + 0.12 * proof + 0.1 if more than one precedent)`, plus 0.1 when a recorded
failure is present, since a failure is stronger evidence than its proof count implies.

Every cited id is cross-checked against the corpus ground truth (76/77 ids), because Hindsight's consolidated
observations carry empty metadata and their ids are a hint rather than a citation-grade reference.

Laya classifies; Hindsight remembers; the ranker decides; the LLM writes prose. Four separate jobs, no
overlap.

## 15. The prompt store (Postgres + pgvector)

A second data store, deliberately separate from Hindsight, holding every prompt run and its embedding so a
new prompt can be cross-referenced against the ones before it.

**Why separate, and the rule that follows.** Hindsight is the company's curated decision memory and the
thing the product reasons over. A prompt the user typed is not company knowledge. If prompts were retained
they would become retrievable evidence, and unreviewed text could end up cited by the ranker. So prompts are
recorded and vectorised in Postgres, and reach Hindsight only through an explicit user action.

Retaining therefore happens in exactly two places, both user-initiated endpoints in `prompt_history.py`:
`POST /api/biz/history/commit` (adding a decision) and `POST /api/biz/history/resolve` (recording its
outcome). The automatic path, `record_and_crossref`, has no Hindsight import at all. That is the guarantee,
and it is checkable by reading one file.

### Embeddings are local, and add no dependency

9router exposes no embeddings route (measured: `/v1/embeddings` returns
`No credentials for provider: openai`, and no model in its list carries an embeddings capability), so
embeddings run in-process. `BAAI/bge-small-en-v1.5`, 384 dimensions, CLS-pooled and L2-normalised so cosine
distance is the honest metric.

The dependency is already there: `torch` and `transformers` ship in the api image for Laya. The prompt store
therefore adds no ML dependency and makes no network call at request time. Weights are fetched once at
**image build time**, the same treatment Laya's ONNX snapshot gets, so a cold start does not pay for it.

Warm cost is small, but the cold call is not: measured **13-61ms** per embed once the model is loaded, and
around **1.3s for the first call**, which includes the lazy load. The model is loaded on first use rather
than at boot, matching Laya, precisely so the container's healthcheck is not held hostage to a model load.
The call runs inside the async request handler, so the cold cost is paid by whoever sends the first prompt
after a restart.

### Schema, and how it evolves

`app/prompts.py` holds both the `CREATE TABLE` and a `MIGRATIONS` string of `ALTER TABLE ... IF NOT EXISTS`
statements. Both run at `ensure_schema()`, which is idempotent and cached, so the table can be extended after
a deployment without a manual step. The index is **HNSW** (`vector_cosine_ops`): adequate at this scale and
it needs no training pass, unlike ivfflat which wants data present before it is useful.

Columns beyond the obvious: `embedding` (nullable), `committed`, `hindsight_doc`, `outcome`, `result_note`,
`resolved_at`, `origin`. `resolved_at` is the marker that separates "committed but the outcome is unknown"
from "closed out", which is what makes the missing-outcome queue queryable.

### Supersede, not duplicate

Resolving a decision re-retains under the **same `document_id`**. Measured directly, because the whole
feature depends on it: two retains with one `document_id` produced **1 document**, not 2. Without that,
closing the loop would duplicate the precedent and inflate the proof count behind a verdict.

### Verification

`api/tests/test_prompt_store.py`, 23 checks, skips cleanly when `PROMPT_DB_URL` is unset. It covers the
behaviours that were previously only hand-verified: an unembedded row is kept but excluded from similarity,
the draft never invents a result or an outcome, `store.get()` finds a row outside the `recent()` window (the
`recent(limit=500)` scan silently 404d past it), the full resolve lifecycle, and that reusing a
`decision_id` supersedes rather than renames.

Measured semantic quality on real prompts: a paraphrased renewal question matched its earlier phrasing at
**0.907**, and an unrelated prompt matched nothing above the cutoff.
