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
