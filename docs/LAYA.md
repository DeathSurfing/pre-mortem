# Laya integration — local System One decisions

Why Laya is in this project, what it replaced, and the exact measured behaviour. Everything here was run,
not read off a README.

## What Laya is

A **System One model**: it does not generate text, it evaluates a state and returns typed answers with
calibrated probabilities. 421M-parameter ModernBERT-large encoder with a typed decision head, Apache-2.0.
Shipped as the ONNX int4 build of `techtheist/laya-onnx`, 275MB.
Three question types, all evaluated in one forward pass:

| type | returns | used here for |
|---|---|---|
| `choice` | probability per option + confidence | `domain` (pricing / hiring / vendor / ...) **and the mode router** |
| `score` | continuous score + distribution + confidence | `reversibility` (Easy / Moderate / Hard) |
| `noul` | probability a statement is true | `gives_value_without_commitment`, `is_high_blast_radius` |

Multiple questions on the same state are evaluated in parallel and cost almost nothing extra.

Laya has two jobs here, and neither is deciding the verdict. It is the **router**: the `choice` question's
`domain_probability` is the number that puts a message into one of three modes, because it separates the
classes cleanly and costs nothing. And it is the **signal provider**: it contributes four attributes the LLM
path never produced (see [Signals it contributes](#signals-it-contributes)). The verdict comes from recorded
outcomes; the LLM writes the sentences.

## What it replaced

Classifying a free-text business decision into a domain used to cost **one LLM call per request**
(`bizlookalike.classify()`). Laya does the domain classification locally, offline, with a calibrated
probability attached, and adds two signals the LLM path never produced: how reversible the decision is,
and whether value is being given away for nothing. It also took over **routing**: deciding whether an
incoming message is a decision to review at all was the LLM's `mode` field, and is now Laya's
`domain_probability` in all but the ambiguous band. The LLM is now used only for what Laya cannot do:
the specific kebab-case `decision_type`, the stated rationale, and arbitration of the ambiguous band.

## Signals it contributes

| Signal | Type | What the app does with it |
|---|---|---|
| `domain_probability` | float | routes the message into `decision` / `query` / `chat`; also the `domain` label |
| `reversibility_label` | Easy / Moderate / Hard | shown with the review; a hard-to-reverse decision is treated as the more serious one |
| `gives_value_without_commitment` | 0..1 | `noul` probability that value is being handed over for nothing |
| `is_high_blast_radius` | 0..1 | `noul` probability that being wrong here is expensive |

These are the only things Laya contributes. It does not pick precedents, it does not score them, and it does
not write the verdict.

## Measured behaviour (ONNX int4, CPU, this container)

Values from the in-repo verification block in `api/app/laya_client.py` (2026-09-27, ONNX int4, CPU):

```text
domain -> "pricing" p=0.9949 confidence=0.9793   (correct for the discount prompt)
reversibility -> score 0.7567, most likely "Moderate"
gives_value_without_commitment -> noul 0.3875
```

Domain classification, measured per prompt:

| Prompt | Laya domain | p | confidence |
|---|---|---|---|
| Acme 30% discount, competitor cheaper | `pricing` | 0.9692 | 0.9148 |
| Hire senior platform engineer, scope later | `hiring` | 0.9936 | 0.9776 |
| Open an office in Lisbon | `expansion` | 0.9560 | 0.8881 |
| (second run, same Lisbon prompt) | `expansion` | 0.6156 | — |

Deployment figures, measured:

```text
LOAD   9.1s   (first call only; lazy-loaded, see below)
PREDICT 1.4-3.0s
PEAK RSS 996MB
```

996MB fits the 4GB cgroup. `torch 2.14.0+cpu` and `libgomp1` are hard runtime dependencies:
`laya/common.py` does `import torch` at module level, and torch's CPU kernels need the OpenMP runtime. The
per-message router probabilities are in [The router](#the-router-laya-decides-the-mode) below.

**Lazy-loaded on purpose.** The ONNX session is built on the first classify, not at boot. So a freshly
started container reports `loaded: false` on `/health` while being perfectly healthy; `enabled: true` is the
honest idle answer, and `loaded` flips true only once a message has actually been classified.

**Do not** use the full torch `Agent` path: loading
`convaiinnovations/laya` in fp32 was OOM-killed here (exit 137). The ONNX int4 build is the deployment
path, and it is also what the upstream `export_web.py` script produces.

## Getting it running (the traps, all hit for real)

1. **It is not on OpenCode Go.** `jev-1.13` and `laya` are absent from `https://opencode.ai/zen/go/v1/models`
   (36 models). Jev exists only on `https://opencode.ai/zen/v1` (44 models) where it is either
   `402 Insufficient account funds` or, as `jev-1.13-free`, `403 FreeTierError: can only be used from
   within OpenCode`. So the hosted route is a dead end for a deployed service. Running Laya locally is the
   working route.
2. **`torch` is unavoidable.** `laya` declares `torch>=2.0.0`, and even `laya.onnx_agent` imports
   `laya.common`, which does `import torch` at module level. Importing the file directly does not dodge it.
   Install with the CPU-only index: `--extra-index-url https://download.pytorch.org/whl/cpu`.
3. **The ONNX weights are third-party, not upstream.** `convaiinnovations/laya` ships safetensors, not ONNX.
   `ONNXAgent` requires a repo containing `rl_agent_config.json`, `tokenizer/` and `encoder/`. Of the
   published mirrors, `techtheist/laya-onnx` has that layout (`en/model_int4.onnx` 275MB,
   `en/model_int8.onnx` 582MB); `receptron/laya-onnx` does **not** and fails with
   `does not contain 'rl_agent_config.json'`.
4. **`onnx_path` must be a local filesystem path.** `ONNXAgent` checks it with `os.path.exists`, while
   `model_id_or_path` is the thing that talks to the Hub. Passing a repo id as `onnx_path` fails with
   `ONNX model not found ... Please run export_onnx.py first`. Snapshot-download first, then pass the
   absolute path.
5. **`subfolder=` changes the resolution.** With `subfolder="en"` the agent appends it and then looks for
   `rl_agent_config.json` inside it, which fails for this repo. Pass the snapshot dir itself and point
   `onnx_path` at `en/model_int4.onnx`.

## The router: Laya decides the mode

`domain_probability` is the router input. Thresholds are constants in `api/app/bizlookalike.py`:

- `LAYA_MODE_DECISION = 0.60`: at or above, the message is a `decision` and gets a full review.
- `LAYA_MODE_CHAT = 0.15`: at or below, it is ordinary conversation.
- Between the two, the band is genuinely ambiguous and the LLM arbitrates; the decision is recorded on the
  classify result as `mode_arbitration`, so an ambiguous routing is auditable rather than invisible.

Measured, production:

| Message | Mode | `domain_probability` |
|---|---|---|
| "hey, how are you doing today?" | `chat` | 0.2923 |
| "thanks, that helps" | `chat` | 0.214 |
| "what did we decide about the Acme renewal?" | `query` | 0.265 |
| "Should I give Acme a 30 percent discount to close the renewal this quarter?" | `decision` | 0.9883 |
| "We are considering opening an office in Lisbon." | `decision` | 0.9422 |

The band where Laya decides alone is kept deliberately tiny. The asymmetry: a message that should have been
reviewed but is answered conversationally silently withholds the entire product, whereas a conversational
message that gets reviewed is merely noisy. Err toward reviewing.

**Tie-break rule, and a real regression.** A message that both proposes an action and asks about the past is
a `decision`, not a `query`. A review cites the records anyway and additionally gives the judgement; `query`
would withhold it. Adding query mode silently degraded preset E ("a partner is asking for exclusivity... I
want to sign it quickly... What has burned us on deals like this before?") from a decision into a query,
because it reads as a history question. It is a `decision`. `api/scripts/mode_check.py` asserts this case.

## `COVERED_DOMAINS`: Laya's label must not override a covered LLM domain

Laya's taxonomy has no bucket for **compliance, security or partnership**. So when the LLM names a domain the
corpus actually covers, that label wins, and Laya's does not override it. `COVERED_DOMAINS` is derived from
the corpus itself (`frozenset(d.domain for d in bizcorpus.corpus())`), not hand-listed.

Getting this wrong made an audit question classify as `launch` at **0.825 confidence** and cite launch
decisions. The confidence number was high, which is exactly why the rule cannot be inferred from the score
alone.

## Caveat worth stating on camera

Laya's own MoE README reports **67.3% vs 59.6%** on 108 hand-labelled cases. That is a real but modest
edge, and the sample is small. So Laya is used where a calibrated probability is genuinely useful and a
mistake is cheap and visible — classification and gating — **not** for the verdict. The verdict stays
deterministic (`rank.py`), computed from the outcomes of recalled precedents. Laya classifies; Hindsight
remembers; the ranker decides; the LLM writes prose. Four separate jobs, no overlap.

If a judge asks "what does the model actually contribute", the honest answer is: it replaces an LLM call
with a local calibrated classifier and gives us a reversibility signal, at 996MB and zero marginal cost.

## Configuration

```bash
LAYA_ENABLED=1                 # set 0 to force the LLM-only path
LAYA_REPO=techtheist/laya-onnx
LAYA_SUBFOLDER=en
LAYA_ONNX_FILE=model_int4.onnx
LAYA_LOCAL_DIR=                # exported by the image entrypoint from /models/laya_path; the weights are
                               # baked into the api image, so no hub call happens at boot
```

`GET /health` reports `laya: {enabled, loaded, error, repo, onnx_file, question_types}` so a deployment
can be checked without reading logs. Expect `enabled: true, loaded: false` on a freshly started container:
the ONNX session is built on the first classify, not at boot. If Laya fails to load for any reason the app
logs it and falls back to the LLM classifier; the product degrades, it does not break.
