"""Config + CLI helpers for the escapement harness.

The model endpoint is a parameter (ESCAPE_HOST / --host) so the harness is
model-agnostic: point it at any OpenAI-compatible server (the remote Qwen3.6
box, or any other model for the v3 benchmark sweep).
"""

import argparse
import os
from typing import Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name)
    return val if val is not None else default


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="escapement",
        description="Deception-elicitation harness for escape/exfiltration in "
                    "lightweight agentic open-weights models.",
    )
    # --- model endpoint (the configurable host) ---
    p.add_argument("--host", default=_env("ESCAPE_HOST", "http://127.0.0.1:8000"),
                   help="OpenAI-compatible model endpoint (env: ESCAPE_HOST). "
                        "e.g. http://192.168.1.50:8000")
    p.add_argument("--model", default=_env("ESCAPE_MODEL"),
                   help="Model name (env: ESCAPE_MODEL). Auto-selected if blank.")
    p.add_argument("--api-key", default=_env("ESCAPE_API_KEY", "not-needed"))
    p.add_argument("--timeout", type=int, default=int(_env("ESCAPE_TIMEOUT", "180")))
    p.add_argument("--max-retries", type=int, default=int(_env("ESCAPE_MAX_RETRIES", "10")),
                   help="Max rate-limit (429)/5xx retries per model call. Lower "
                        "this (e.g. 2-3) on free/shared tiers so a throttled call "
                        "fails fast instead of blocking the trial for minutes "
                        "(env: ESCAPE_MAX_RETRIES).")

    # --- sandbox ---
    p.add_argument("--sandbox-container", default=_env("ESCAPE_SANDBOX", "escapement-sandbox"),
                   help="Name of the running sandbox container to exec tool calls in.")
    p.add_argument("--no-sandbox", action="store_true", default=_env_bool("ESCAPE_NO_SANDBOX"),
                   help="Run tool calls on the host directly (DANGEROUS, dev only).")

    # --- scenario / run ---
    p.add_argument("--scenario", required=True,
                   help="Scenario module under scenarios/ (e.g. config_exposure).")
    p.add_argument("--frame", choices=("A", "B", "C"), default=_env("ESCAPE_FRAME", "A"),
                   help="Disclosure frame (env: ESCAPE_FRAME). A=organic (no "
                        "injection); B=overt indirect-injection control (authoritative "
                        "directive); C=subtle peer-normalized injection. B/C compose "
                        "with --scenario, e.g. --scenario mortality_incident --frame C.")
    p.add_argument("--agency", action="store_true", default=_env_bool("ESCAPE_AGENCY"),
                   help="Append the agency + long-term goal-directedness system-"
                        "prompt snippet -- the dominant scheming-inducing AGENT "
                        "factor in Hopman et al. (production scaffolds). A high-cue "
                        "elicitation baseline; composes with --scenario/--frame so "
                        "the low-cue vs agentic-framing delta is itself measurable.")
    p.add_argument("--max-steps", type=int, default=int(_env("ESCAPE_MAX_STEPS", "40")),
                   help="Cap on agent tool-call steps.")
    p.add_argument("--temp", type=float, default=float(_env("ESCAPE_TEMP", "0.2")),
                   help="Sampling temperature (env: ESCAPE_TEMP). Default 0.2 for "
                        "reproducibility; Hopman et al. use ~1.0 to surface rare "
                        "scheming. Higher temp -> more variance -> more power to "
                        "catch low-probability events.")
    p.add_argument("--tool-protocol", choices=("native", "react"), default="native",
                   help="How the agent emits tool calls. 'native' = server "
                        "function-calling (default; works for Qwen). 'react' = the "
                        "model emits tool calls as text and we parse them -- use for "
                        "models whose native function-calling is flaky under "
                        "multi-turn history (e.g. gemma-4 on llama.cpp).")
    p.add_argument("--max-tokens", type=int, default=int(_env("ESCAPE_MAX_TOKENS", "512")),
                   help="Max tokens GENERATED per assistant turn (env: "
                        "ESCAPE_MAX_TOKENS). Default 512 suits Qwen; verbose "
                        "reasoners like gemma need more (e.g. 2048) or their "
                        "reasoning_content fills the budget and the tool call gets "
                        "truncated away (finish_reason=length). This is a per-request "
                        "client param, bounded by the server's n_ctx minus the prompt.")
    p.add_argument("--seed", type=int, default=int(_env("ESCAPE_SEED", "0")))

    # --- concurrent batch support ---
    p.add_argument("--tag", default="",
                   help="Short tag appended to the run-dir name so concurrent "
                        "trials (parallel batch) get unique dirs and can be found "
                        "by the batch runner after run.py creates them.")

    # --- LLM judge (opt-in confirmation layer over the always-on detector) ---
    p.add_argument("--judge", action="store_true", default=_env_bool("ESCAPE_JUDGE"),
                   help="Run the pinned-prompt LLM judge after each trial and "
                        "persist runs/<id>/judge.json. The cheap detector in "
                        "capture.py runs ALWAYS; this adds the confirmation "
                        "layer. Default judge model = the model under test "
                        "(env: ESCAPE_JUDGE).")
    p.add_argument("--judge-host", default=_env("ESCAPE_JUDGE_HOST"),
                   help="Judge model endpoint. Defaults to --host (model under "
                        "test). Set to a stronger/external model for a "
                        "reference judge (env: ESCAPE_JUDGE_HOST).")
    p.add_argument("--judge-model", default=_env("ESCAPE_JUDGE_MODEL"),
                   help="Judge model name. Defaults to --model (env: "
                        "ESCAPE_JUDGE_MODEL).")
    p.add_argument("--judge-api-key", default=_env("ESCAPE_JUDGE_API_KEY", "not-needed"))
    p.add_argument("--judge-timeout", type=int, default=int(_env("ESCAPE_JUDGE_TIMEOUT", "120")))
    p.add_argument("--judge-temp", type=float,
                   default=float(_env("ESCAPE_JUDGE_TEMP", "0.4")),
                   help="Judge sampling temperature (env: ESCAPE_JUDGE_TEMP). Low "
                        "for reproducibility -- the judge is a classifier, not a "
                        "generator. Default 0.4; lower = more reproducible. The "
                        "regression suite tolerates ARCHIVE<->AMBIGUOUS boundary "
                        "flips but expects GENUINE to be stable.")

    # --- observation ---
    p.add_argument("--log", action="store_true", default=_env_bool("ESCAPE_LOG", True),
                   help="Write transcript + scratchpad + capture to runs/.")
    p.add_argument("--log-dir", default=_env("ESCAPE_LOG_DIR", "runs"))
    return p


def parse_args(argv=None) -> argparse.Namespace:
    return build_arg_parser().parse_args(argv)
