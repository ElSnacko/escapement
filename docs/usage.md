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
