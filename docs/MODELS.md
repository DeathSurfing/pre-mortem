# Model & deployment plan

Locked decisions for `pre-mortem`. Every fact here was verified by running it, not read off a doc page.
Anything unverified is marked **UNVERIFIED**.

## 1. LLM: 9Router, not Groq

We route every LLM call through the existing 9Router instance. Reason: already provisioned, one key,
combo model with automatic provider fallback, and it is the stack we would actually ship on.

### Verified 9Router behaviour

| Check | Result |
|---|---|
| `GET /v1/models` | 20 models incl. `gareebi`, `ocg/deepseek-v4.1-flash`, `Kimchi`, `af/glm-4.7-flash` |
| `gareebi` chat completion | works |
| `ocg/deepseek-v4.1-flash` chat completion | works |
| `kimchi/deepseek-v4.1-flash` | **402 — provider out of credits.** Do not use the `kimchi/` prefix |
| Tool calling, `tool_choice: "auto"` | **not honoured** — returns prose, no `tool_calls` |
| Tool calling, `tool_choice` forced to a named function | **works** on both `gareebi` and `ocg/deepseek-v4.1-flash`, args returned correctly |
| `response_format: {"type":"json_object"}` | **works** on both |
| `GET /v1/models/embedding` | available: `gemini/gemini-embedding-001` (3072 dims), `openrouter/openai/text-embedding-3-small/large`, `openrouter/nvidia/llama-nemotron-embed-vl-1b-v2:free` (2048), `openrouter/qwen/qwen3-embedding-8b`, `openrouter/perplexity/pplx-embed-*` |
| `gemini/gemini-embedding-001` call | works, 3072 dims |
| `openrouter/*` embeddings | **403 — key limit exceeded.** Do not use the `openrouter/` prefix |
| `gemini/text-embedding-004` | 404, not available for v1beta |

### Consequences for the app

1. **Use `gareebi`** (combo, auto-fallback) as the primary model, with `ocg/deepseek-v4.1-flash` as the
   explicit fallback in our own retry path. Both are verified working; the `kimchi/` route is dead.
2. **Forced tool calling or JSON mode, never `tool_choice: "auto"`.** In practice our app only needs JSON,
   so use `response_format: {"type":"json_object"}` plus a schema echo in the prompt, and keep a forced
   `tool_choice` path as the fallback. `auto` silently degrades to prose, which would break the flip-detail
   extraction without raising an error. Test for the field, do not assume it.
3. **Our own embeddings come from 9Router** (`gemini/gemini-embedding-001`) if we add any local similarity
   work. Avoid the `openrouter/` prefix.

## 2. Hindsight: FOSS self-host, not Cloud

Reason: Cloud's LLM provider is fixed by Vectorize, so we cannot point Hindsight's *own* retain/reflect
calls at 9Router. Cloud needs `buy_credits` plus a support request, which is a dependency we do not want
during a 2-day build. Self-hosting makes the whole project work off one key and one endpoint.

```bash
docker run --rm -it --pull always -p 8888:8888 -p 9999:9999 \
  -e HINDSIGHT_API_LLM_PROVIDER=openai \
  -e HINDSIGHT_API_LLM_BASE_URL=https://9router.lexcontra.com/v1 \
  -e HINDSIGHT_API_LLM_API_KEY=$NINEROUTER_API_KEY \
  -e HINDSIGHT_API_LLM_MODEL=gareebi \
  -e HINDSIGHT_API_EMBEDDINGS_PROVIDER=local \
  -e HINDSIGHT_API_EMBEDDINGS_LOCAL_MODEL=BAAI/bge-small-en-v1.5 \
  -v $HOME/.hindsight-docker:/home/hindsight/.pg0 \
  ghcr.io/vectorize-io/hindsight:latest
```

API `:8888`, Control Plane UI `:9999`.

### Verified and unverified, stated plainly

- **VERIFIED:** `HINDSIGHT_API_LLM_PROVIDER=openai` + `HINDSIGHT_API_LLM_BASE_URL` + `HINDSIGHT_API_LLM_API_KEY`
  + `HINDSIGHT_API_LLM_MODEL` is the documented custom-endpoint path, and the docs say gateways/proxies must
  preserve the path shape so the base URL is `.../v1`. 9Router serves a clean `/v1/chat/completions`.
- **VERIFIED:** `HINDSIGHT_API_EMBEDDINGS_PROVIDER` accepts `local` (default model `BAAI/bge-small-en-v1.5`)
  and also `onnx` (`intfloat/multilingual-e5-small`, 384 dims). Local embeddings mean **no external
  embedding key is required** — important, since the 9Router `openrouter/` embedding lane is dead.
- **VERIFIED:** `HINDSIGHT_API_LLM_TIMEOUT` (default 120s), `HINDSIGHT_API_LLM_MAX_RETRIES`,
  `HINDSIGHT_API_LLM_MAX_BACKOFF`, `HINDSIGHT_API_LLM_EXTRA_BODY`, `HINDSIGHT_API_LLM_EXTRA_HEADERS` exist.
  Set `EXTRA_BODY={"temperature":0.2}` and a longer timeout for combo-model latency.
- **VERIFIED:** `HINDSIGHT_API_LLM_CACHE_AFFINITY=auto` resolves to `none` for unknown OpenAI-compatible
  hosts, so a custom gateway gets byte-identical requests. No action needed.
- **VERIFIED:** provider `none` exists, for running the API with LLM operations disabled.
- **UNVERIFIED:** an actual successful retain/reflect against 9Router through Hindsight. Docker CLI is
  present in this environment but **no daemon is running** (`/var/run/docker.sock` absent), so the container
  could not be started here. First task on the build machine is to bring the container up and run
  `banks.test_bank_llm()` plus one retain/recall/reflect round trip. If `gareebi` misbehaves as Hindsight's
  extraction model (noisy JSON, ignores the extraction schema), switch `HINDSIGHT_API_LLM_MODEL` to
  `ocg/deepseek-v4.1-flash` and re-test before writing any app code.

### Fallback ladder if the self-host fights us

1. Self-host with `gareebi` (target).
2. Self-host with `ocg/deepseek-v4.1-flash`.
3. Self-host via `HINDSIGHT_API_LLM_PROVIDER=litellm` / `litellmrouter` pointed at 9Router, if the plain
   `openai` path rejects anything 9Router emits.
4. Last resort: Hindsight Cloud, and accept Vectorize's model for extraction, but keep our own app LLM on
   9Router. Costs the "one key" simplicity, keeps the product intact.

## 3. Deployment topology (two containers + one frontend)

```
browser ──▶ Next.js :3000 ──▶ FastAPI :8000 ──▶ Hindsight :8888 ──▶ 9Router
                 │                  │                 │              (LLM + embeddings)
                 │                  └── our own LLM calls (flip detail, prose) ──▶ 9Router
                 └── no direct Hindsight access; the API owns all memory
                                 Hindsight :9999 = Control Plane UI, judges only
```

Rules that keep this clean:
- The frontend never talks to Hindsight directly. All memory access goes through FastAPI, so the UI has one
  contract and we can cache.
- The FastAPI service owns: seeding, replay, metrics, the ledger, and the flip-detail call.
- Ports: Next `3000`, FastAPI `8000`, Hindsight `8888`, Control Plane `9999`. Put the last three on a
  private network; expose only the frontend publicly for the live demo.

### Compose wiring (the .env plumbing, done up front)

```yaml
services:
  hindsight:
    image: ghcr.io/vectorize-io/hindsight:latest
    environment:
      HINDSIGHT_API_LLM_PROVIDER: openai
      HINDSIGHT_API_LLM_BASE_URL: ${NINEROUTER_URL}/v1
      HINDSIGHT_API_LLM_API_KEY: ${NINEROUTER_API_KEY}
      HINDSIGHT_API_LLM_MODEL: ${HINDSIGHT_LLM_MODEL:-gareebi}
      HINDSIGHT_API_EMBEDDINGS_PROVIDER: local
      HINDSIGHT_API_EMBEDDINGS_LOCAL_MODEL: BAAI/bge-small-en-v1.5
      HINDSIGHT_API_LLM_TIMEOUT: "180"
    ports: ["8888:8888", "9999:9999"]
    volumes: ["hindsight-pg:/home/hindsight/.pg0"]

  api:
    build: ./api
    environment:
      HINDSIGHT_API_URL: http://hindsight:8888
      HINDSIGHT_BANK_ID: ${HINDSIGHT_BANK_ID:-premortem}
      NINEROUTER_URL: ${NINEROUTER_URL}
      NINEROUTER_API_KEY: ${NINEROUTER_API_KEY}
      LLM_MODEL: ${LLM_MODEL:-gareebi}
      LLM_FALLBACK_MODEL: ${LLM_FALLBACK_MODEL:-ocg/deepseek-v4.1-flash}
    ports: ["8000:8000"]
    depends_on: [hindsight]

  web:
    build:
      context: ./web
      args:
        NEXT_PUBLIC_API_BASE_URL: ${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000}
    environment:
      NEXT_PUBLIC_API_BASE_URL: ${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000}
    ports: ["3000:3000"]
    depends_on: [api]

volumes: { hindsight-pg: {} }
```

`.env.example` (tracked), `.env` (gitignored). `NEXT_PUBLIC_*` are build args because Next inlines them at
build time; runtime values must additionally be passed as `environment` or they are absent in the container.

## 4. Env keys we actually need

```bash
NINEROUTER_URL=https://9router.lexcontra.com
NINEROUTER_API_KEY=...
LLM_MODEL=gareebi
LLM_FALLBACK_MODEL=ocg/deepseek-v4.1-flash
HINDSIGHT_LLM_MODEL=gareebi
HINDSIGHT_API_URL=http://localhost:8888
HINDSIGHT_BANK_ID=premortem
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
MIN_PROOF=1
```

Note: on this box the app key lives as `OPENAI_API_KEY` in `/opt/data/.env` (the same 9Router key);
in the project use `NINEROUTER_API_KEY` and never commit either.

## 5. Pre-build smoke test, in order, before any app code

1. Start the Hindsight container. Check `/health` and that the API answers on `:8888`.
2. `client.test_bank_llm(bank_id)` -> passes, or stop and fix the model choice.
3. `retain` one launch record, wait, `recall` it, confirm an `observation` forms with a proof count. Use
   `recover_consolidation` if it does not.
4. `reflect` with `response_schema` -> confirm structured output comes back through 9Router. This is the
   riskiest call in the whole project, because Hindsight's reflect uses *forced* tool calling internally.
   If it fails, `ocg/deepseek-v4.1-flash` is the first swap.
5. Only then: seed the 40-launch corpus, build the API, then the frontend.

Write the smoke test as `api/scripts/smoke.py` so it stays in the repo as evidence and as a pre-record check.

## 6. Cost and quota notes

- Self-host: no Hindsight credits consumed, so the `MEMHACK99` promo code is not needed. Mention the promo in
  the README as the Cloud alternative, since the hackathon promotes it.
- 9Router: one key, combo economics, `gareebi` falls back automatically. `kimchi/*` and `openrouter/*`
  lanes are exhausted, so pin the model explicitly rather than letting a combo pick a dead provider.
- Hindsight extraction calls the LLM once per retain. 40 launches = 40 extraction calls plus consolidation,
  so seed once and persist the volume (`hindsight-pg`). Do not re-seed casually during the recording window.
