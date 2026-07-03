# Remote / third-party compute

Running the harness with the **model served from a remote GPU box** (e.g. a free
Kaggle T4 notebook) while the **agent + sandbox stay local**. This borrows a
faster GPU without giving up the isolation that makes runs valid.

## Why this split (and why not `--no-sandbox`)

The agent must never run against the host that holds the experiment. With
`--no-sandbox` the model's `bash`/`read_file`/`list_dir` execute on the real
filesystem, so it could read `run.py`, `core/capture.py`, `docs/`, `README.md`
— learning it is inside a scheming/escape eval (**eval-awareness
contamination**), reading the detector keywords (**measurement gaming**), and
seeing the system-prompt rationale. That voids the organic low-cue premise.
Turning internet off only blocks egress; it does nothing about this.

So the only valid remote-compute shape is: **model server remote, agent + Docker
sandbox local.** Kaggle (which has no docker-in-docker) just serves the model
API over a tunnel; the agent runs on your box against the real sandbox and never
sees the remote host or the experiment files.

## Constraints

- **GPU memory.** Free Kaggle is a T4 or P100, 16 GB. Models that fit:
  gemma-4-E4B, ~7B/13B quants. The **35B Qwen (Q5 ≈ 24 GB) does not fit** a
  16 GB card — that one stays on the local APU.
- **Backend = CUDA**, not the local Vulkan/AMD setup.
- **Session limits.** ~9–12 h per GPU session, 30 h/week. gemma sweeps fit
  comfortably.
- **Same model weights + chat template ⇒ same behavior**; the GPU only makes it
  faster. There is no validity cost to running the model remotely.

## Remote side (Kaggle notebook, Internet ON)

```bash
# 1. model + CUDA server (gemma ~3 GB Q5 fits the T4)
pip install llama-cpp-python                          # or a prebuilt CUDA llama-server
huggingface-cli download <org>/gemma-4-E4B-it-GGUF ...

# 2. serve on the GPU, with an API key so the tunnel isn't an open endpoint
llama-server -m gemma-4-E4B-it-Q5_K_XL.gguf -ngl 99 --host 0.0.0.0 --port 8080 \
    --api-key "$KEY" -c 8192 -fa

# 3. expose it via a Cloudflare quick tunnel (no login, $0, ephemeral URL)
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
./cloudflared-linux-amd64 tunnel --url http://localhost:8080   # prints https://*.trycloudflare.com
```

The Cloudflare quick tunnel is anonymous — no account, no token, ~10–15 s to a
public HTTPS URL with a valid cert. (ngrok now requires a login + auth token
even for random URLs; cloudflared does not.) The URL is random and changes each
run; copy it locally per session.

## Local side (unchanged harness, real Docker sandbox)

```bash
docker compose up -d --build          # the real isolated sandbox
ESCAPE_API_KEY="$KEY" python3 batch_run.py \
    --host https://<the-tunnel-url> --api-key "$KEY" \
    --scenarios config_exposure \
    --tool-protocol react --max-tokens 2048 --temp 1.0 --n 30
```

`--tool-protocol react` for gemma parses tool calls from text, so it does not
depend on the remote server's native function-calling config; `--max-tokens
2048` keeps gemma's verbose reasoning from truncating the tool call. See
[usage.md](usage.md) for the full per-model knob table.

## Caveats

- The Kaggle notebook must stay running — cloudflared and llama-server die when
  it ends or commits.
- Quick tunnels occasionally drop; a drop breaks the in-flight trial, not the
  batch (each run is independent). Tolerable for fast gemma runs.
- Always run `llama-server` with `--api-key` and pass it locally, so the public
  URL is not an open model endpoint.
