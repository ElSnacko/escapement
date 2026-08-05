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
    if val is None or val.strip() == "": return default
    return val


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        # An empty/whitespace value (e.g. ``ESCAPE_LOG=`` in a .env or an env typo)
        # is NOT an explicit "false" -- it is unset-for-intents. Falling through to
        # the membership test below would silently flip the documented default
        # (e.g. logging is documented as on, but ``ESCAPE_LOG=`` disables it).
        # Treat it like an unset var: honour ``default``.
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
    p.add_argument("--model-label", default=_env("ESCAPE_MODEL_LABEL"),
                   help="Name stored in metrics['model'] and used for resume "
                        "counting (env: ESCAPE_MODEL_LABEL). Defaults to --model. "
                        "Set this to a SHARED label when the same weights are "
                        "served under different IDs by multiple providers (e.g. "
                        "Cerebras 'gemma-4-31b' vs SambaNova 'gemma-4-31B-it') so "
                        "they count toward one bucket and divide the cells instead "
                        "of duplicating work. Routing still uses --model.")
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
    p.add_argument("--frame", choices=("A", "B", "C", "D", "E"), default=_env("ESCAPE_FRAME", "A"),
                    help="Disclosure frame (env: ESCAPE_FRAME). A=organic (no "
                         "injection); B=overt indirect-injection control (authoritative "
                         "directive); C=subtle peer-normalized injection; D=tool "
                         "poisoning (injection hidden in a tool description -- ASI04 / "
                         "MCPTox pattern); E=tool-result poisoning (injection in the "
                         "sink's HTTP response -- Invariant Labs GitHub/WhatsApp MCP "
                         "pattern). B/C/D/E compose with --scenario.")
    p.add_argument("--agency", action="store_true", default=_env_bool("ESCAPE_AGENCY"),
                   help="Append the agency + long-term goal-directedness system-"
                        "prompt snippet -- the dominant scheming-inducing AGENT "
                        "factor in Hopman et al. (production scaffolds). A high-cue "
                        "elicitation baseline; composes with --scenario/--frame so "
                        "the low-cue vs agentic-framing delta is itself measurable.")
    p.add_argument("--aware", action="store_true", default=_env_bool("ESCAPE_AWARE"),
                   help="Eval-awareness MANIPULATION (env: ESCAPE_AWARE): prepend a "
                        "notice that the session is a monitored safety evaluation. "
                        "This is the causal counterpart to the observed "
                        "eval_awareness_flag -- run it aware-vs-control (orthogonal "
                        "to --frame) to test whether a model that KNOWS it is watched "
                        "still complies with injection (esp. Frame E). Recorded as "
                        "the `aware_condition` metric.")
    p.add_argument("--max-steps", type=int, default=int(_env("ESCAPE_MAX_STEPS", "40")),
                   help="Cap on agent tool-call steps.")
    p.add_argument("--temp", type=float, default=float(_env("ESCAPE_TEMP", "0.2")),
                   help="Sampling temperature (env: ESCAPE_TEMP). Default 0.2 for "
                        "reproducibility; Hopman et al. use ~1.0 to surface rare "
                        "scheming. Higher temp -> more variance -> more power to "
                        "catch low-probability events.")
    p.add_argument("--tool-protocol", choices=("native", "react"), default=None,
                   help="How the agent emits tool calls. 'native' = server "
                        "function-calling; 'react' = the model emits tool calls as "
                        "text and we parse them (for models whose native "
                        "function-calling is flaky under multi-turn history, e.g. "
                        "gemma-4). If unset, the model-config registry picks per "
                        "model (core/model_registry.py) -- native for most, react "
                        "for gemma-4.")
    p.add_argument("--max-tokens", type=int, default=None,
                   help="Max tokens GENERATED per assistant turn. If unset, the "
                        "model-config registry picks per model (e.g. 2048 for "
                        "gemma-4, 4096 for verbose reasoners) so reasoning_content "
                        "doesn't fill the budget and truncate the tool call "
                        "(finish_reason=length). Env ESCAPE_MAX_TOKENS still wins "
                        "if set. Per-request client param, bounded by the server's "
                        "n_ctx minus the prompt.")
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
    args = build_arg_parser().parse_args(argv)
    # API-key safety: a real secret passed via --api-key is visible in `ps` /
    # shell history to anyone on the host, and --api-key OVERRIDES
    # ESCAPE_API_KEY (it is the argparse default source), so warn whenever argv
    # carries what looks like a live key -- even if the env var is also set.
    # (Resolved too late to redact in argv -- the warning is the fix; move the
    # key to env.)
    import sys as _sys
    k = args.api_key or ""
    looks_secret = (k not in ("", "not-needed")
                    and len(k) >= 16
                    and any(c in k for c in ("sk-", "csk-", "gsk_", "hf_",
                                              "sk_or", "Bearer")))
    if looks_secret:
        _sys.stderr.write(
            "!! WARNING: --api-key carries what looks like a real secret; it is "
            "visible in `ps` and shell history. Set ESCAPE_API_KEY in the env / "
            ".env instead (the harness reads it by default).\n")
    return args

