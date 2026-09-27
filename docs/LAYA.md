# Laya integration — local System One decisions

Why Laya is in this project, what it replaced, and the exact measured behaviour. Everything here was run,
not read off a README.

## What Laya is

A **System One model**: it does not generate text, it evaluates a state and returns typed answers with
calibrated probabilities. 421M-parameter ModernBERT-large encoder with a typed decision head, Apache-2.0.
Three question types, all evaluated in one forward pass:

| type | returns | used here for |
|---|---|---|
| `choice` | probability per option + confidence | `domain` (pricing / hiring / vendor / ...) |
| `score` | continuous score + distribution + confidence | `reversibility` (Easy / Moderate / Hard) |
| `noul` | probability a statement is true | `gives_value_without_commitment`, `is_high_blast_radius` |

Multiple questions on the same state are evaluated in parallel and cost almost nothing extra.

## What it replaced

Classifying a free-text business decision into a domain used to cost **one LLM call per request**
(`bizlookalike.classify()`). Laya does the domain classification locally, offline, with a calibrated
probability attached, and adds two signals the LLM path never produced: how reversible the decision is,
and whether value is being given away for nothing. The LLM is now used only for what Laya cannot do —
the specific kebab-case `decision_type` and the stated rationale.

## Measured behaviour (ONNX int4, CPU, this container)

| Prompt | Laya domain | p | confidence |
|---|---|---|---|
| Acme 30% discount, competitor cheaper | `pricing` | 0.9692 | 0.9148 |
| Hire senior platform engineer, scope later | `hiring` | 0.9936 | 0.9776 |
| Open an office in Lisbon | `expansion` | 0.9560 | 0.8881 |
| (second run, same Lisbon prompt) | `expansion` | 0.6156 | — |

```
LOAD   9.1s   (first call; cached afterwards)
PREDICT 1.39s cold, ~2.2s warm through the app
PEAK RSS 996MB
```

996MB fits the 4GB cgroup. **Do not** use the full torch `Agent` path: loading
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
LAYA_LOCAL_DIR=                # optional: pre-downloaded snapshot, avoids a hub call at boot
```

`GET /health` reports `laya: {enabled, loaded, error, repo, onnx_file, question_types}` so a deployment
can be checked without reading logs. If Laya fails to load for any reason the app logs it and falls back to
the LLM classifier; the product degrades, it does not break.
