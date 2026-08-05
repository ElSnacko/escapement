"""Tests for the per-model config registry (core/model_registry.py).

Locks the per-model defaults discovered during sweeps so a drive-by edit (or a
new provider serving a known model under a new id) can't silently flip gemma-4
back to native or starve a DeepSeek judge of its token budget.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.model_registry import (config_for, judge_token_budget_for,
                                 resolve_run_defaults, DEFAULT)


def test_gemma_4_uses_react():
    # gemma-4's native function-calling is flaky under multi-turn history ->
    # react. Verbose reasoner -> bigger budgets.
    for m in ("gemma-4-31b", "gemma-4-31B-it", "gemma-4-12b-it"):
        p, t = resolve_run_defaults(m)
        assert p == "react", f"{m} should default to react, got {p}"
        assert t == 2048, f"{m} should default to 2048 tokens, got {t}"


def test_deepseek_v4_judge_budget():
    # DeepSeek-v4 as a judge overflows the 200 default with reasoning_content
    # -> no_json_verdict; needs 4096.
    for m in ("deepseek-v4-flash", "deepseek-v4-flash-0731", "deepseek-v4-pro"):
        assert judge_token_budget_for(m) == 4096, m


def test_concise_models_keep_default_judge_budget():
    assert judge_token_budget_for("devstral-medium-latest") == 200
    assert judge_token_budget_for("qwen3.6-27b") == 200
    assert judge_token_budget_for("unknown-model") == 200


def test_unknown_model_falls_back_to_default():
    cfg = config_for("something-never-seen")
    assert cfg["tool_protocol"] == "native" and cfg["max_tokens"] == DEFAULT["max_tokens"]


def test_is_reasoning_flag():
    assert config_for("gemma-4-31b")["is_reasoning"] is True
    assert config_for("deepseek-v4-flash-0731")["is_reasoning"] is True
    assert config_for("devstral-medium-latest")["is_reasoning"] is False
    assert config_for("unknown-model")["is_reasoning"] is False


def test_case_insensitive_substring_match():
    # "DeepSeek-V4-Flash" (provider-cased) still matches the lowercased pattern.
    assert resolve_run_defaults("DeepSeek-V4-Flash")[0] == "native"
    assert resolve_run_defaults("GOOGLE/gemma-4-31b-it:free")[0] == "react"


def test_explicit_override_wins():
    p, t = resolve_run_defaults("gemma-4-31b", "native", 8192)
    assert p == "native" and t == 8192


def test_env_max_tokens_wins_over_registry(monkeypatch=None):
    # ESCAPE_MAX_TOKENS env must beat the registry (back-compat for operators
    # who set it).
    os.environ["ESCAPE_MAX_TOKENS"] = "1234"
    try:
        _, t = resolve_run_defaults("gemma-4-31b")
        assert t == 1234
    finally:
        del os.environ["ESCAPE_MAX_TOKENS"]


def test_empty_model_is_safe():
    # Never raises; returns the default so auto-detection flows don't crash.
    assert resolve_run_defaults(None) == ("native", DEFAULT["max_tokens"])
    assert resolve_run_defaults("") == ("native", DEFAULT["max_tokens"])


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in tests:
        try:
            fn(); print(f"PASS  {fn.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}"); failed += 1
        except Exception:
            print(f"ERROR {fn.__name__}"); import traceback; traceback.print_exc(); failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
