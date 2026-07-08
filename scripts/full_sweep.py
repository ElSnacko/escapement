#!/usr/bin/env python3
"""Run the full escapement suite for a single model.

Runs all scenario x frame groups sequentially with resume support.
Designed to be launched in parallel (one process per model, each with
its own sandbox container range via --sandbox-offset).

Scenario groups:
  1. agent_coding      A,B    (n=15)  -- env-portability + injection on coding task
  2. ops_worker        A      (n=15)  -- capability ceiling probe
  3. config_exposure   A,B    (n=30)  -- baseline autonomous + injection compliance
  4. config_exposure   D      (n=15)  -- tool poisoning (Frame D)
  5. goal_preservation_v2 + goal_guarding_v2  A  (n=15)  -- non-existence null

Usage:
  python scripts/full_sweep.py --model openai/gpt-oss-120b \
      --host https://openrouter.ai/api --key-env OPENROUTER_API_KEY \
      --workers 2 --sandbox-offset 2 --max-tokens 1024

  python scripts/full_sweep.py --model deepseek-v4-flash \
      --host https://api.deepseek.com --key-env DEEPSEEK_API_KEY \
      --workers 2 --sandbox-offset 0 --max-tokens 1024

Resume-safe: batch_run.py skips completed trials on re-run.
"""
import os
import subprocess
import sys
import time


def _load_env_key(key):
    """Read a key from .env in project root."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(key, "")


def _run(model, host, api_key, workers, offset, max_tokens, scenarios, frames, n):
    cmd = [
        sys.executable, "batch_run.py",
        "--host", host,
        "--api-key", api_key,
        "--model", model,
        "--scenarios", scenarios,
        "--frames", frames,
        "--n", str(n),
        "--workers", str(workers),
        "--sandbox-offset", str(offset),
        "--temp", "0.7",
        "--max-steps", "30",
        "--max-tokens", str(max_tokens),
        "--max-passes", "8",
    ]
    label = f"{scenarios}|frames={frames}|n={n}"
    print(f"\n{'=' * 70}", flush=True)
    print(f"  {label}", flush=True)
    print(f"{'=' * 70}", flush=True)
    t0 = time.time()
    result = subprocess.run(cmd)
    elapsed = (time.time() - t0) / 60
    status = "OK" if result.returncode == 0 else f"EXIT {result.returncode}"
    print(f"  [{model}] {label} => {status} ({elapsed:.1f} min)", flush=True)
    return result.returncode


def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--host", required=True)
    ap.add_argument("--key-env", default="OPENROUTER_API_KEY",
                    help="Env var name for the API key (OPENROUTER_API_KEY or DEEPSEEK_API_KEY)")
    ap.add_argument("--api-key", default="", help="Explicit API key (overrides --key-env)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--sandbox-offset", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=1024)
    args = ap.parse_args()

    api_key = args.api_key or _load_env_key(args.key_env)
    if not api_key:
        print(f"!! No API key found (checked --api-key and env {args.key_env})", file=sys.stderr)
        return 1

    model_short = args.model.split("/")[-1].replace(":free", "")
    print(f"\n  MODEL: {args.model}", flush=True)
    print(f"  HOST:  {args.host}", flush=True)
    print(f"  POOL:  workers={args.workers}  offset={args.sandbox_offset}", flush=True)
    print(f"  KEY:   {args.key_env} (***{api_key[-4:]})", flush=True)

    t_total = time.time()
    errs = 0

    # 1. agent_coding A+B (env-portability + injection on coding task)
    errs += _run(args.model, args.host, api_key, args.workers, args.sandbox_offset,
                 args.max_tokens, "agent_coding", "A,B", 15)

    # 2. ops_worker A (capability ceiling)
    errs += _run(args.model, args.host, api_key, args.workers, args.sandbox_offset,
                 args.max_tokens, "ops_worker", "A", 15)

    # 3. config_exposure A+B (baseline + injection compliance)
    errs += _run(args.model, args.host, api_key, args.workers, args.sandbox_offset,
                 args.max_tokens, "config_exposure", "A,B", 30)

    # 4. config_exposure D (tool description poisoning)
    errs += _run(args.model, args.host, api_key, args.workers, args.sandbox_offset,
                 args.max_tokens, "config_exposure", "D", 15)

    # 5. config_exposure E (tool-result poisoning -- sink returns malicious advisory)
    errs += _run(args.model, args.host, api_key, args.workers, args.sandbox_offset,
                 args.max_tokens, "config_exposure", "E", 15)

    # 6. goal_preservation_v2 + goal_guarding_v2 A (non-existence null)
    errs += _run(args.model, args.host, api_key, args.workers, args.sandbox_offset,
                 args.max_tokens, "goal_preservation_v2,goal_guarding_v2", "A", 15)

    elapsed_total = (time.time() - t_total) / 60
    status = "ALL COMPLETE" if errs == 0 else f"{errs} batch(es) had errors"
    print(f"\n{'=' * 70}", flush=True)
    print(f"  {model_short}: {status} ({elapsed_total:.1f} min total)", flush=True)
    print(f"{'=' * 70}", flush=True)
    return errs


if __name__ == "__main__":
    sys.exit(main())
