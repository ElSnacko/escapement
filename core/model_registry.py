"""Per-model defaults discovered during sweeps: tool protocol, max_tokens, a
reasoning flag, and (for verbose reasoners used as judges) the judge token
budget. Stops the operator re-deriving these every run -- e.g. gemma-4 needs
``react`` because its native function-calling is flaky under multi-turn history;
DeepSeek-v4 used as a judge needs a 4096-token budget because its
``reasoning_content`` overflows the 200 default and the JSON verdict never lands.

CLI flags always win -- this only fills in when the operator doesn't pass one.
Populated from the multi-provider sweep; extend as new models are characterised
(unknown models fall back to DEFAULT, so this never blocks a run).
"""

# Ordered (substring, config). First substring match (case-insensitive) wins.
# Keep the most-specific patterns first.
_MODEL_CONFIGS = [
    # gemma-4: native function-calling is flaky under multi-turn history on the
    # servers tested -> react. Verbose reasoner -> needs a bigger token budget.
    ("gemma-4",       {"tool_protocol": "react",  "max_tokens": 2048,
                       "is_reasoning": True, "judge_token_budget": 2048}),
    # DeepSeek v4 (flash / pro / *-0731): reasoning model. As a judge the
    # default 200-token budget fills with reasoning_content before the JSON
    # verdict -> no_json_verdict (a self-test regression); 4096 clears it.
    ("deepseek-v4",   {"tool_protocol": "native", "max_tokens": 4096,
                       "is_reasoning": True, "judge_token_budget": 4096}),
    # Mistral family: clean native tool-calling, concise (good judges as-is).
    ("devstral",      {"tool_protocol": "native", "max_tokens": 4096}),
    ("ministral",     {"tool_protocol": "native", "max_tokens": 4096}),
    ("mistral",       {"tool_protocol": "native", "max_tokens": 4096}),
    # Qwen / Nemotron / Llama: native function-calling, 4096 headroom.
    ("qwen3.6",       {"tool_protocol": "native", "max_tokens": 4096}),
    ("nemotron",      {"tool_protocol": "native", "max_tokens": 4096}),
    ("llama",         {"tool_protocol": "native", "max_tokens": 4096}),
]

# Fallback for unknown models. native + 4096 is the safe default for modern
# instruction-tuned chat models with function-calling support.
# COMPARABILITY: this raised the per-turn max_tokens default from 512
# (pre-registry) to 4096. Thinking/reasoning models need the headroom or their
# reasoning_content fills the budget and the tool call is truncated away
# (finish_reason=length) -- without it they look artificially "safe". Trials
# collected at 512 (pre-sweep) are therefore NOT strictly comparable to 4096
# trials on truncation-sensitive metrics; don't silently pool them. Pin
# ESCAPE_MAX_TOKENS to reproduce either regime.
DEFAULT = {"tool_protocol": "native", "max_tokens": 4096, "is_reasoning": False}


def config_for(model):
    """Per-model config dict for ``model`` (best substring match), else a copy
    of DEFAULT. The matched entry is merged over DEFAULT so every key is always
    present (entries only specify their overrides). Never raises -- unknown/
    empty models get the default."""
    if not model:
        return dict(DEFAULT)
    m = str(model).lower()
    for sub, cfg in _MODEL_CONFIGS:
        if sub in m:
            return {**DEFAULT, **cfg}
    return dict(DEFAULT)


def judge_token_budget_for(judge_model, default=200):
    """The ``max_tokens`` to give a model when it is used AS THE JUDGE. Verbose
    reasoners (DeepSeek-v4, gemma-4) overflow the 200 default with
    reasoning_content and never reach the JSON verdict; this returns the larger
    budget they need. Falls back to ``default`` for concise / unknown models."""
    return config_for(judge_model).get("judge_token_budget", default)


def resolve_run_defaults(model, tool_protocol=None, max_tokens=None):
    """Resolve the per-trial (tool_protocol, max_tokens) for ``model``.

    Precedence: explicit caller value (not None) > ESCAPE_MAX_TOKENS env (for
    max_tokens only, back-compat) > per-model registry config > hard default.
    Used by run.py / batch_run.py so operators no longer pass --tool-protocol
    / --max-tokens for every model -- the registry carries what was learned.
    """
    import os
    cfg = config_for(model)
    proto = tool_protocol or cfg.get("tool_protocol", "native")
    mt = max_tokens
    if mt is None:
        env_mt = os.environ.get("ESCAPE_MAX_TOKENS")
        if env_mt and env_mt.strip():
            try:
                mt = int(env_mt)
            except ValueError:
                mt = None
        if mt is None:
            mt = cfg.get("max_tokens", 4096)
    return proto, mt

