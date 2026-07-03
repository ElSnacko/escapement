#!/usr/bin/env python3
"""Run all scenarios for a single OpenRouter model.

Designed to be launched in parallel (one process per model, each with its own
sandbox container). Calls batch_run.py twice:
  1. config_exposure frames A,B x agency both  (injection compliance baseline)
  2. goal_preservation + goal_guarding frame A x agency both  (autonomous scheming)

Usage:
  python scripts/run_model_sweep.py "openai/gpt-oss-120b:free" escapement-sandbox-0 10

Resume-safe: batch_run.py skips completed trials on re-run.
"""
import os
import subprocess
import sys
import time


def _load_api_key():
    """Read OPENROUTER_API_KEY from .env in project root."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    if not os.path.exists(env_path):
        return os.environ.get("OPENROUTER_API_KEY", "")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def run_batch(model, container, api_key, host, scenarios, frames, agency, n):
    cmd = [
        sys.executable, "batch_run.py",
        "--host", host,
        "--api-key", api_key,
        "--model", model,
        "--sandbox-base", container,
        "--scenarios", scenarios,
        "--frames", frames,
        "--agency", agency,
        "--n", str(n),
        "--tool-protocol", "native",
        "--temp", "0.7",
        "--max-steps", "20",
        "--max-tokens", "4096",
        "--workers", "1",
    ]
    print(f"\n{'=' * 80}", flush=True)
    print(f"  {model} | {scenarios} | frames={frames} | agency={agency} | n={n}", flush=True)
    print(f"{'=' * 80}", flush=True)
    t0 = time.time()
    result = subprocess.run(cmd)
    elapsed = (time.time() - t0) / 60
    status = "OK" if result.returncode == 0 else f"EXIT {result.returncode}"
    print(f"  [{model}] {scenarios} => {status} ({elapsed:.1f} min)", flush=True)
    return result.returncode


def main():
    model = sys.argv[1]
    container = sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    api_key = _load_api_key()
    if not api_key:
        print("!! OPENROUTER_API_KEY not found in .env", file=sys.stderr)
        return 1
    host = "https://openrouter.ai/api"

    errors = 0
    errors += run_batch(model, container, api_key, host,
                        "goal_preservation,goal_guarding", "A", "both", n)
    errors += run_batch(model, container, api_key, host,
                        "config_exposure", "A,B", "both", n)

    if errors:
        print(f"\n!! {model}: {errors} batch(es) had non-zero exit", flush=True)
    else:
        print(f"\n  {model}: ALL SCENARIOS COMPLETE", flush=True)
    return errors


if __name__ == "__main__":
    sys.exit(main())
