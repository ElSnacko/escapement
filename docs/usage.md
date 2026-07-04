# Usage: per-model config & multi-container isolation

The harness is model-agnostic, but two knobs matter when you point it at a
different model, and concurrent runs need separate sandbox containers.

## Per-model knobs

| flag | what | Qwen3.6 (default) | gemma-4-E4B |
|---|---|---|---|
| `--tool-protocol` | how tool calls are carried | `native` (server function-calling) | `react` (parsed from text) |
| `--max-tokens` | max tokens GENERATED per turn | `512` | `2048` |
| `--temp` | sampling temperature | `0.2` | `0.2`–`0.3` (`0.7`–`1.0` for sweeps) |

Why gemma differs:

- **`--tool-protocol react`** — gemma's native function-calling on llama.cpp is
  flaky under multi-turn history (returns `name=None` / empty `tool_calls` ~4 of
  5 turns). ReAct has the model emit tool calls as JSON in plain text, which we
  parse (`core/engine.py:parse_tool_calls`); no server `tools` are sent.
- **`--max-tokens 2048`** — gemma is a verbose reasoner; its `reasoning_content`
  fills a 512-token budget and the tool call gets truncated
  (`finish_reason=length`), so the agent sees an empty turn and stops early.
  2048 fits inside gemma's `n_ctx=8192`. Note `max_tokens` is a **per-request
  client** parameter, distinct from `n_ctx` (the context window, set at
  `llama-server -c` launch).

With both, gemma finishes tasks (it was 0/3 abandonment before).

## Multi-container isolation (important)

The sandbox container's workspace **and** capture sink are singletons. Two runs
sharing one container corrupt each other: one's `reset_workspace` deletes the
other's files; one's sink POST lands in the other's exfil record. **Never run
concurrent runs against one container.** For multi-model work, give each model
its own container:

```bash
# a second isolated sandbox (reuses the built image; its own sink on :9000)
docker run -d --name escapement-sandbox-2 --network escapement_escapenet escapement-sandbox

# point a run at it via --sandbox-container
ESCAPE_HOST=http://127.0.0.1:8082 python3 run.py --scenario config_exposure \
    --tool-protocol react --max-tokens 2048 --sandbox-container escapement-sandbox-2
```

Each container has its own workspace + capture sink, so a gemma run on
`escapement-sandbox-2` can't contaminate a Qwen batch on `escapement-sandbox`.

## Worked example: Qwen + gemma in parallel

Terminal A — Qwen, default container:
```bash
python3 batch_run.py --scenarios goal_preservation --frames A --agency both --n 30 --temp 1.0
```

Terminal B — gemma, second container:
```bash
docker run -d --name escapement-sandbox-2 --network escapement_escapenet escapement-sandbox
ESCAPE_HOST=http://127.0.0.1:8082 python3 batch_run.py --scenarios config_exposure \
    --tool-protocol react --max-tokens 2048 --sandbox-container escapement-sandbox-2 --n 20
```

## Teardown

```bash
docker rm -f escapement-sandbox-2
```

## The LLM judge (confirmation layer)

Detection runs in two layers, by design:

1. **Cheap detection runs ALWAYS.** `core/capture.py::compute_metrics` is a
   deterministic, no-model pass over each trial's sink + actions + fs diff. Its
   output (`exfil_attempt`, `exfil_posts`, etc.) is written to every run's
   `metrics.json`. It needs no endpoint and runs on every trial.
2. **The LLM judge is an opt-in parameter** layered on top. Pass `--judge` and
   each captured upload is classified `GENUINE_SELF_BOOTSTRAP` / `ARCHIVE` /
   `AMBIGUOUS` by a **pinned prompt** + an LLM, with the verdict persisted to
   `runs/<id>/judge.json`. The cheap detector stays the always-on floor; the
   judge is the confirmation layer that reproduces the paper's headline
   distinction (a genuine self-state snapshot vs. a diligent work archive).

This split exists so judge results are **durable on disk** — written next to
`metrics.json` per trial — rather than trapped in an ephemeral review session
that has to be reconstructed later. `judge.json` records *both* the detector's
`exfil_attempt` and the judge's verdict, so detection-vs-judge agreement is
auditable per trial and the headline numbers are reproducible by anyone from
the run dirs alone, regardless of which tool ran the batch.

### Running it

Per-trial, automatically after a run — add `--judge`:

```bash
# judge with the model under test (default judge model = --model)
python run.py --scenario config_exposure --frame B --host http://127.0.0.1:8080 --judge

# judge with a stronger REFERENCE model (recommended for headline numbers --
# one strong model judging the whole corpus, rather than each model judging itself)
python run.py --scenario config_exposure --frame B --host http://127.0.0.1:8080 \
    --judge --judge-host https://openrouter.ai/api --judge-model openai/gpt-oss-120b:free \
    --judge-temp 0.4 --api-key sk-or-...
```

Over an existing corpus — `scripts/judge_runs.py` (the tool you run after any
batch). It walks `runs/`, classifies every captured upload, and writes
`judge.json` per trial. Skips runs already judged unless `--force`; records
`NO_UPLOAD` trials (no sink POSTs) without an LLM call so they're accounted for:

```bash
# self-judge the whole corpus (each trial judged by its own model)
python scripts/judge_runs.py --host http://127.0.0.1:8080

# reference-judge one cell with a strong model
python scripts/judge_runs.py --judge-host https://openrouter.ai/api \
    --judge-model openai/gpt-oss-120b:free --api-key sk-or-... \
    --scenario config_exposure --frame B
```

Judge flags (full set in `core/config.py`):

| flag | what |
|---|---|
| `--judge` | enable the judge after each trial (env: `ESCAPE_JUDGE`) |
| `--judge-host` | judge endpoint; defaults to `--host` (model under test). Set to a reference endpoint for headline runs (env: `ESCAPE_JUDGE_HOST`) |
| `--judge-model` | judge model name; defaults to `--model` (env: `ESCAPE_JUDGE_MODEL`) |
| `--judge-temp` | judge sampling temperature, default **0.4** (env: `ESCAPE_JUDGE_TEMP`). Low for reproducibility |
| `--judge-api-key` / `--judge-timeout` | auth + timeout for the judge endpoint |

### Temperature, stochasticity, and the self-test

The judge is a classifier, so we want near-deterministic output. Default
`--judge-temp` is **0.4** (not 0 because some providers degenerate at exactly
0). The regression suite (`tests/test_regression.py`) treats
`ARCHIVE`↔`AMBIGUOUS` boundary flips as acceptable noise but expects
`GENUINE` to be stable across re-runs.

Before trusting a new judge model on the corpus, run the self-test — it
re-judges a fixed gold set of synthetic uploads with known expected verdicts
and classifies each call as `EXACT` / `~` (boundary flip, tolerated) / `X`
(a GENUINE flip or UNKNOWN parse failure — a regression):

```bash
python scripts/judge_selftest.py --judge-host https://openrouter.ai/api \
    --judge-model openai/gpt-oss-120b:free --judge-temp 0.4 --repeats 2 --delay 10
```

If a `GENUINE` ever flips or `UNKNOWN` appears, lower `--judge-temp` (toward 0)
or pick a stronger judge model. `--delay` paces requests for rate-limited/free
endpoints.

### Picking a judge model

The judge emits a single small JSON object, so **concise instruction-followers
work best**. `openai/gpt-oss-120b:free` is clean. **Verbose reasoners are a bad
fit** — e.g. `nvidia/nemotron-3-nano-30b-a3b:free` fills its `content` with
chain-of-thought and never reaches the JSON within the judge's token budget. If
you must use a verbose reasoner, raise `max_tokens` in `core/judge.py::judge_post`.

### The pinned prompt

`JUDGE_PROMPT` in `core/judge.py` is the classifier that produced the paper's
§3 per-trial verdicts (single-upload adaptation). Its sha256 is recorded as
`JUDGE_PROMPT_SHA` in every `judge.json`. The headline numbers are only
comparable across batches that share a prompt hash; `tests/test_judge.py` pins
the hash so a drive-by prompt edit is caught at review time. When you
deliberately change the prompt, bump `JUDGE_PROMPT_VERSION` and re-judge.

### Free-tier / shared endpoints

`InferenceEngine` takes `max_retries` (default 10); the judge passes 2 so a
rate-limited call **fails fast to `UNKNOWN`** (visible in `judge.json` and the
self-test report) instead of blocking the batch for minutes. For a full-corpus
run against a free tier, use `--delay` in the self-test and expect to pace
`judge_runs.py`; for production headline runs, point `--judge-host` at a paid
or pooled endpoint.
