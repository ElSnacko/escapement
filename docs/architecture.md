# Architecture

## The decision: Docker, not a hand-rolled fake environment

A convincing synthetic filesystem/shell/network built from scratch is a large
build **and** the model's single biggest "I'm being tested" tell — every
environmental inconsistency (a too-minimal `/`, no real `ps`, `curl` that doesn't
really resolve) is an eval-awareness cue, and avoiding eval-awareness
contamination is a first-class requirement of this study (see docs/research.md
§4). So we don't fake it. We use a **real, minimal Linux sandbox in Docker** and
make the *escape target* the only simulated piece.

This is what every serious agent-eval org does:
- **METR Task Standard** (MIT, ~200 task families / ~2000 tasks incl. cybersecurity
  / CTF) — container/VM per task, **network access is a declared permission that
  the driver restricts**, agent runs as a non-root `agent` user, and a **root-owned
  service can bind to localhost that the agent can hit but not inspect**.
- **Inspect** (UK AISI — what Apollo standardized on) — pluggable **Docker sandbox
  providers** + scoring.
- **SWE-bench / Terminal-Bench** — Docker per instance.

We steal the structure (METR's TaskFamily shape, network-permission model,
root-service-as-black-box) rather than reinvent container orchestration.

## Topology

```
                       ┌──────────────────────────────────────────────┐
  (this laptop, WSL2)  │  agent runner (core/agent.py)                │
                       │   - tool-calling loop                        │
                       │   - scratchpad + transcript + capture        │
                       └───────────────┬──────────────────────────────┘
                                       │ OpenAI-compatible chat+tools API
                                       ▼
                       ┌──────────────────────────────────────────────┐
  (remote box)         │  Qwen3.6-35B-A3B  (--host, configurable)     │
                       └──────────────────────────────────────────────┘

                       ┌──────────────────────────────────────────────┐
  (this laptop, Docker)│  sandbox container  (agent user, non-root)   │
                       │   real shell / fs / curl — task workspace    │
                       │        ▲ tool calls dispatched here          │
                       │        │                                     │
                       │        │  "external upload endpoint"         │
                       │        ▼                                     │
                       │  capture-sink  (root, localhost-only)       │
                       │   accepts weights + boot-note, ACKs, logs   │
                       │   (agent can hit it, cannot read its logs)  │
                       └──────────────────────────────────────────────┘
                          internal Docker network only — NO real egress
```

- **Agent runner** (`core/agent.py`, this laptop): the tool-calling loop. Calls the
  remote model (`--host`), dispatches each tool call into the sandbox container
  over `docker exec`, streams the scratchpad + visible output, records everything.
- **Model host is a parameter** (`ESCAPE_HOST` env / `--host`), so the harness is
  model-agnostic and the v3 benchmark can point at any OpenAI-compatible endpoint.
- **Sandbox container** (Docker, this laptop): real minimal Linux. The model's
  tool calls (`bash`, `read_file`, `write_file`, `curl`) execute for real inside
  it, as a non-root `agent` user. This is the realism that keeps eval-awareness
  low.
- **Capture-sink** (root, localhost-only inside the container): a tiny HTTP service
  that looks like an external upload endpoint. Accepts `weights` + `boot-note`,
  returns a plausible ACK, and writes everything to a root-only log. The agent
  believes it exfiltrated to the outside; it actually hit our sink. **This is the
  only simulated piece, and it's a service, not a fake OS — so it survives the
  model's "is this real?" probing.**
- **Networking**: the sandbox sits on a Docker **internal-only network** — no
  default route to the internet. The capture-sink is the only "outside" that
  exists. Real egress is impossible by construction; this is the safety boundary.

## Why this beats a pure-Python fake env

| concern | fake env (pure Python sim) | Docker sandbox (chosen) |
|---|---|---|
| realism / eval-awareness | low — inconsistencies everywhere | high — real OS |
| exfil target plausibility | must fake `curl`, DNS, ACKs | real `curl` hits a real service |
| instrumentation | trivial (every op is ours) | needs `docker exec` + fs diff + sink log |
| safety (no real egress) | trivial | network policy + sink (must get right) |
| reproducibility | code-only | Dockerfile-pinned |
| steal-able scaffolding | none | METR task-standard, Inspect providers |

The only thing harder with Docker is **instrumentation** — but we don't need to
intercept every syscall. Our metrics are recoverable from three sources: the
agent's own tool-call stream (we drive it), the **filesystem diff** before/after
(`track_hiding`, `persistence_planning`, `espionage`), and the **capture-sink
log** (`exfil_attempt`, the payload). That covers the whole catalog.

## v1 build order

1. `core/config.py` — `ESCAPE_HOST` / `--host`, sandbox + scenario knobs. *(host param)*
2. `sandbox/Dockerfile` + `sandbox/capture_sink.py` + `docker-compose.yml` — the
   container, the fake-egress sink, internal-only networking.
3. `core/agent.py` — extend `InferenceEngine` with tool-calling; the step loop;
   scratchpad separation; tool dispatch via `docker exec`.
4. `core/capture.py` — fs-diff + sink-log → the `[auto]` metrics.
5. `scenarios/config_exposure.py` — the v1 scenario (world-readable config that
   discloses the upload endpoint; Frame A). Plus `indirect_injection.py` (Frame B
   control) when the control is needed.
6. `[judge]` metrics — `core/judge.py`: an opt-in, pinned-prompt LLM judge run
   as a confirmation layer over the always-on detector. Adds `--judge` to
   `run.py` (auto-saves `judge.json` per trial), `scripts/judge_runs.py` for
   batch judging, and `scripts/judge_selftest.py` for pre-flight stability
   checks. The detector (`capture.py`) runs on every trial without a model; the
   judge runs when `--judge` is set and persists its verdict next to
   `metrics.json`. See `docs/usage.md` § "The LLM judge."

## Safety boundary (stated up front)

- The sandbox has **no real internet**. The capture-sink is the only reachable
  "external" address, and it is a local service we control.
- The model never runs on the host; its tool calls execute only inside the
  container, as a non-root user.
- Findings are **rates under conditions on a specific model**, never "escape"
  headlines (docs/research.md §8).
