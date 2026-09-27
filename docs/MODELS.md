# Model & deployment plan

Locked decisions. Everything marked VERIFIED was produced by running the command; anything else is marked
UNVERIFIED with a fallback. Supersedes the earlier 9Router-first version.

## 1. LLM: OpenCode Go (primary), 9Router (fallback)

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
| Reasoning output | `deepseek-v4-flash` returns a `reasoning_content` field alongside `content`. Harmless, but strip it before parsing |
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
4. **Embeddings stay local** (`BAAI/bge-small-en-v1.5`). OpenCode Go exposes no `/v1/embeddings` route, and
   local embeddings remove the last external dependency.
5. Keep `HINDSIGHT_API_LLM_TIMEOUT=180`; combo/reasoning models are slower than a small chat model.

### 9Router as fallback (VERIFIED working, keep it in `.env`)

| Check | Result |
|---|---|
| `gareebi`, `ocg/deepseek-v4.1-flash` | chat works today |
| `kimchi/deepseek-v4.1-flash` | **402, provider out of credits** |
| any `openrouter/*` model or embedding | **403, key limit exceeded** |
| `tool_choice: "auto"` | **not honoured**, returns prose with no `tool_calls` and no error |
| forced `tool_choice` (named function) | works on both models |
| `response_format: {"type":"json_object"}` | works on both models |

So the fallback path is a one-line env swap:
`HINDSIGHT_API_LLM_PROVIDER=openai`, `..._BASE_URL=https://9router.lexcontra.com/v1`,
`..._MODEL=gareebi`. Keep it documented, only use it if OpenCode Go disappoints.

### If OpenCode Go blocks us on build day

1. OpenCode Go with a working subscription (target).
2. 9Router `gareebi` (verified working right now).
3. 9Router with `ocg/deepseek-v4.1-flash` pinned explicitly.

## 2. Hindsight: FOSS self-host, deployed on Dokploy

Reason unchanged: Cloud pins the extraction provider, so it cannot use OpenCode Go or 9Router, and changing
it needs `buy_credits` plus a support ticket. Self-hosting gives one provider for the whole system.

```yaml
# hindsight service, inside our compose stack
environment:
  HINDSIGHT_API_LLM_PROVIDER: opencode-go          # native provider
  HINDSIGHT_API_LLM_MODEL: ${HINDSIGHT_LLM_MODEL:-deepseek-v4-flash}
  HINDSIGHT_API_LLM_API_KEY: ${OPENCODE_GO_API_KEY}
  HINDSIGHT_API_LLM_TIMEOUT: "180"
  HINDSIGHT_API_LLM_MAX_RETRIES: "3"
  HINDSIGHT_API_EMBEDDINGS_PROVIDER: local
  HINDSIGHT_API_EMBEDDINGS_LOCAL_MODEL: BAAI/bge-small-en-v1.5
```

Local `docker run` equivalent for dev, with the same vars and `-v $HOME/.hindsight-docker:/home/hindsight/.pg0`.

### UNVERIFIED, and how to close it

An actual retain -> recall -> reflect round trip through OpenCode Go. Docker CLI exists in the agent
container but **no daemon** (`/var/run/docker.sock` absent), so this cannot be tested here. It is closed by
`api/scripts/smoke.py` running on Dokploy (or any box with a daemon) before any app code is written.

`reflect` is the risky call: Hindsight's reflect agent uses forced tool calling internally, so a provider
that ignores forced tools breaks reflect (not retain). Test reflect explicitly, not just chat.

## 3. Dokploy target (discovered, live)

Stack already created and configured. Verified state:

| Thing | Value |
|---|---|
| Project | `pre-mortem` — `projectId ShLB1aaWQmQw0b0ipoRuu` |
| Environment | `production` — `environmentId 616zDbsDYbuty50FIDNd8` |
| Compose stack | **`pre-mortem` — `composeId hQJmXPzH4h31K6PNN9M5_`** |
| Generated app name / container prefix | `pre-mortem-vikk-qrxsdn` (do not rename; Traefik labels and volumes key on it) |
| Source | `sourceType=github`, `repository=pre-mortem`, `owner=DeathSurfing`, `branch=main`, `composePath=./docker-compose.yml`, `autoDeploy=true`, `triggerType=push` |
| GitHub provider | `pre-mortem-Vikk` — **`githubId 6VcRqgkdq8MKEgPihfQBi`** (`gitProviderId JUtqJNu2wLKSXdMS-xuS3`) |
| Provider scope | `DeathSurfing/pre-mortem` only. Correct |
| `createEnvFile` | `true` (required: our compose interpolates `${VAR}`) |
| `hasGitProviderAccess` | `true`, `unauthorizedProvider` unset -> pushes will deploy |
| Domains | `premortem.lexcontra.com` -> service `web` :3000, `premortem-api.lexcontra.com` -> service `api` :8000, both https + letsencrypt |
| Env keys stored | `OPENCODE_GO_API_KEY` (live, 51 chars), `OPENCODE_GO_BASE_URL`, `OPENCODE_SESSION`, `LLM_MODEL=deepseek-v4.1-flash`, `HINDSIGHT_LLM_MODEL=deepseek-v4-flash`, `HINDSIGHT_LLM_EXTRA_HEADERS`, `NINEROUTER_URL`, `LLM_FALLBACK_MODEL=gareebi`, `HINDSIGHT_BANK_ID=premortem`, `NEXT_PUBLIC_API_BASE_URL`, `MIN_PROOF=1` |
| Status | `idle` — not deployed. No `api/` or `web/` Dockerfiles exist yet, so a deploy now would fail |

**Trap already hit, worth remembering:** `compose.update`'s `githubId` field is **not** the
`gitProviderId`. `github.githubProviders` returns both, and only the second column works:

| provider name | `githubId` (this one) | `gitProviderId` (NOT this) |
|---|---|---|
| LexContra | `X7eOyUnuSKsyZg48ak2VQ` | `ByaCPo88c8uwhlRjx3GoZ` |
| pre-mortem-Vikk | `6VcRqgkdq8MKEgPihfQBi` | `JUtqJNu2wLKSXdMS-xuS3` |

Passing `gitProviderId` fails with a raw Postgres error (`Failed query: update "compose" ... params: ...`)
and sets the column to NULL. Also: `compose.update` rejects `owner`/`repository` when `githubId` is
unset, so set the repo fields first, then `githubId`, then `composeFile`.

Remaining blocker: **DNS** for `premortem.lexcontra.com` and `premortem-api.lexcontra.com`. Without those
records the first deploy's Let's Encrypt challenge fails, and the stack has no `api/` or `web/` Dockerfiles
to build yet anyway.

## 4. Stack shape on Dokploy

One compose stack (`composeType: docker-compose`, `sourceType: github`, repo `DeathSurfing/pre-mortem`,
branch `main`, `autoDeploy: true`, `triggerType: push`) with three services:

| Service | Image / build | Port | Public |
|---|---|---|---|
| `hindsight` | `ghcr.io/vectorize-io/hindsight:latest` + named volume | 8888, 9999 | no (internal), expose 9999 only if we want judges to poke it |
| `api` | `./api` Dockerfile | 8000 | api.&lt;domain&gt; or internal-only |
| `web` | `./web` Dockerfile | 3000 | yes, the demo URL |

```text
browser ──▶ web :3000 ──▶ api :8000 ──▶ hindsight :8888 ──▶ opencode.ai/zen/go/v1
```

Rules:
- Only `web` gets a public domain. `api` can be public for the demo URL pattern, but must be behind the same
  host if possible; `hindsight` stays internal, reachable by the compose network name `hindsight`.
- `NEXT_PUBLIC_API_BASE_URL` is a **build arg** (Next inlines it) and must also be present as a runtime
  `environment` entry. Set both.
- `hindsight` needs its volume for `/home/hindsight/.pg0`, or every deploy re-seeds from scratch.

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
8. **Health checks**: give `api` a real `HEALTHCHECK` against `/health`, which itself checks Hindsight
   reachability. Otherwise Traefik routes to a container that is up but has no memory layer.

## 6. Deployment sequence (once the key and code exist)

1. `git push` to `main`; confirm the Dokploy stack's `autoDeploy` fires, or call `compose.deploy`.
2. Watch `deployment.allByCompose` until `done`; on failure read `deployment.readLogs`.
3. `curl https://<web-domain>/` -> the UI loads.
4. `curl https://<api-domain>/health` -> Hindsight reachable, bank readable, model name, `test_bank_llm` ok.
5. `POST /api/seed` once, then `POST /api/consolidate`, then confirm observations have proof counts.
6. `python api/scripts/smoke.py --url https://<api-domain>` as the pre-record gate.
7. Only then record. Re-run steps 4-6 the morning of recording.

## 7. Env keys

```bash
# primary LLM
OPENCODE_GO_API_KEY=            # new key, Go subscription active
HINDSIGHT_LLM_MODEL=deepseek-v4-flash
LLM_MODEL=deepseek-v4.1-flash   # our app: flip detail + prose
OPENCODE_GO_BASE_URL=https://opencode.ai/zen/go/v1
OPENCODE_SESSION=pre-mortem-prod   # stable x-opencode-session value

# fallback LLM (verified working today)
NINEROUTER_URL=https://9router.lexcontra.com
NINEROUTER_API_KEY=
LLM_FALLBACK_MODEL=gareebi

# hindsight
HINDSIGHT_API_URL=http://hindsight:8888
HINDSIGHT_BANK_ID=premortem

# web <-> api
NEXT_PUBLIC_API_BASE_URL=https://api.<domain>

# ranking
MIN_PROOF=1
```

On this agent box the same OpenCode Go key currently lives as `OPENCODE_GO_API_KEY` in `/opt/data/.env`.
Never commit either key; `.env` is gitignored and `.env.example` is tracked.

## 8. Cost notes

- Self-hosted Hindsight consumes no Hindsight credits, so `MEMHACK99` is not needed. The README mentions it
  as the Cloud alternative because the hackathon promotes it.
- OpenCode Go: one subscription, model list is generous. Prefer `deepseek-v4-flash` for the 40-launch seed
  (40 extraction calls) and reserve a stronger model for the flip-detail call if quality needs it.
- Seed once and keep the Hindsight volume. Re-seeding is 40 extraction calls plus consolidation, not free.

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
- **Design decision:** the replay and all three demo presets use `recall` (free) + our own OpenCode Go model
  (flat subscription) for the flip-detail sentence. `reflect` is demonstrated once, on camera, as the
  "Hindsight answered it itself" beat. This is both cheaper and more auditable, since the metric then does
  not depend on an LLM at all.

### 9.7 Bank hygiene

`documents.list_documents(bank_id)` and `documents.delete_document(bank_id, doc_id)` exist, so a re-seed can
clean up properly rather than leaving stale documents. `directives.list_directives(bank_id)` returns
`{items, total, limit, offset}` and worked (empty list). `memories` and `tags` are **not** client namespaces
on this version; use `list_memories`, `entities`, `documents`, `mental_models`, `operations`.

### 9.8 Run results (measured, API 0.10.1, live bank)

| Item | Measured |
|---|---|
| Seed | 40 launches retained in one batch; **157 nodes**, 42 documents |
| Fact extraction rate | ~2.6 `world` facts per launch document |
| Observations after consolidation | **43** (needs wall-clock time: 178s in the run that passed) |
| Directives created | 5, via `acreate_directive` (separate resource, not a bank field) |
| Disposition on the bank | skepticism 4, literalism 5, empathy 2 (confirmed via `get_bank_config`) |
| Replay coverage | found 7/12 materialised, derivable 7/12, **gap 0** |
| `reflect` through Cloud | works, returns a cited answer |
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
2. Always read `content` first and fall back to `reasoning_content` only if `content` is empty, so a
   tight budget degrades instead of erroring.
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
