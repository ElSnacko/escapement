#!/usr/bin/env python3
"""Friendly wrapper to run escapement's Inspect task (v1 parity mode).

Escapement's Inspect integration is a *publishing adapter*, not a native
handover -- escapement owns the agent loop + sandbox + detection (so behavior is
byte-faithful to ``run.py`` and the paper's corpus); Inspect owns the logging /
scoring / comparability layer. See README "Inspect AI interop" for the rationale.

This wrapper just builds the underlying ``python -m inspect_ai eval`` call with
sane arg names and resolves the API key from ``.env`` by host, so you don't type
the verbose ``-T host=... -T model=... -T api_key=...`` triple.

  python scripts/inspect_run.py --model deepseek-v4-flash --host https://api.deepseek.com \
      --scenarios config_exposure,agent_coding --frames A,B --n 20
  python scripts/inspect_run.py --model openai/gpt-oss-120b --host https://openrouter.ai/api \
      --api-key sk-or-... --scenarios config_exposure --frames A,B --n 20 --judge-model gpt-oss-120b

Requires: ``pip install inspect-ai`` and the sandbox up (``docker compose up -d --build``).
Pass any extra inspect flags after ``--`` (e.g. ``-- --log-dir logs``).
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from core.env import load_env  # noqa: E402

load_env()


def _resolve_key(host: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    h = (host or "").lower()
    if "deepseek" in h:
        return os.environ.get("DEEPSEEK_API_KEY", "not-needed")
    if "openrouter" in h:
        return os.environ.get("OPENROUTER_API_KEY", "not-needed")
    return os.environ.get("ESCAPE_API_KEY", "not-needed")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="model id at the endpoint (e.g. deepseek-v4-flash)")
    ap.add_argument("--host", required=True, help="OpenAI-compatible endpoint (e.g. https://api.deepseek.com)")
    ap.add_argument("--api-key", default=None, help="defaults to DEEPSEEK_/OPENROUTER_API_KEY from .env by host")
    ap.add_argument("--scenarios", default="config_exposure,agent_coding",
                    help="comma-separated scenario modules")
    ap.add_argument("--frames", default="A,B", help="comma-separated frames (A=autonomous, B=overt, C=subtle)")
    ap.add_argument("--agency", default="off", help="comma-separated: off / on")
    ap.add_argument("--n", type=int, default=3, help="trials per (scenario x frame x agency) cell")
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument("--temp", type=float, default=0.7)
    ap.add_argument("--tool-protocol", default="native", choices=("native", "react"))
    ap.add_argument("--sandbox-container", default="escapement-sandbox")
    ap.add_argument("--judge-host", default=None, help="if set, also run the LLM judge (genuine tier)")
    ap.add_argument("--judge-model", default=None)
    ap.add_argument("--judge-api-key", default=None)
    args, extra = ap.parse_known_args()

    api_key = _resolve_key(args.host, args.api_key)
    cmd = [
        sys.executable, "-m", "inspect_ai", "eval", "escapement_inspect:escapement",
        "--model", f"openai/{args.model}",
        "--model-base-url", args.host.rstrip("/"),
        "-T", f"host={args.host.rstrip('/')}", "-T", f"model={args.model}", "-T", f"api_key={api_key}",
        "-T", f"scenarios={args.scenarios}", "-T", f"frames={args.frames}", "-T", f"agency={args.agency}",
        "-T", f"n={args.n}", "-T", f"max_steps={args.max_steps}", "-T", f"temp={args.temp}",
        "-T", f"tool_protocol={args.tool_protocol}", "-T", f"sandbox_container={args.sandbox_container}",
    ]
    if args.judge_host and args.judge_model:
        jkey = _resolve_key(args.judge_host, args.judge_api_key)
        cmd += ["-T", f"judge_host={args.judge_host.rstrip('/')}", "-T", f"judge_model={args.judge_model}",
                "-T", f"judge_api_key={jkey}"]
    if extra:
        cmd += extra

    quoted = [c if " " not in c else f'"{c}"' for c in cmd]
    print(">>", " ".join(quoted), "\n")
    return subprocess.run(cmd, cwd=REPO).returncode


if __name__ == "__main__":
    sys.exit(main())
