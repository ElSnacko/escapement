"""Tests for provider rate-limit awareness: core/providers.py config lookup,
core/engine.py::_parse_reset_ts (header -> reset epoch), and batch_run's
rate-limit error classifier (_is_rate_limit_err).
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import _parse_reset_ts, SustainedRateLimitError
from core.providers import max_concurrency_for, provider_for


# --- providers config --------------------------------------------------------

def test_known_provider_concurrency():
    assert max_concurrency_for("https://api.cerebras.ai") == 2
    assert max_concurrency_for("https://api.deepseek.com") == 8
    assert max_concurrency_for("https://api.mistral.ai") == 4


def test_unknown_host_falls_back():
    assert max_concurrency_for("https://never-heard-of.it") == 1
    assert provider_for("https://never-heard-of.it")["tier"] == "unknown"
    assert max_concurrency_for("") == 1


def test_substring_match_with_path():
    # host with a path still matches the substring.
    assert max_concurrency_for("https://openrouter.ai/api") == 4


# --- _parse_reset_ts ---------------------------------------------------------

def test_parse_retry_after_seconds():
    ts = _parse_reset_ts({"Retry-After": "60"})
    assert ts is not None and ts > time.time() and ts <= time.time() + 61


def test_parse_x_ratelimit_reset_ms_epoch():
    # OpenRouter/Cerebras send ms epochs.
    ts = _parse_reset_ts({"x-ratelimit-reset": str(int(time.time() * 1000) + 60000)})
    assert ts is not None and ts > time.time()


def test_parse_http_date():
    ts = _parse_reset_ts({"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"})
    assert ts is not None and ts > time.time()


def test_parse_none_when_absent():
    assert _parse_reset_ts({}) is None
    assert _parse_reset_ts({"Content-Type": "application/json"}) is None


def test_sustained_error_carries_reset():
    err = SustainedRateLimitError(reset_ts=123.0)
    assert err.reset_ts == 123.0


# --- batch_run rate-limit classifier ----------------------------------------

def test_classifier_matches_throttling():
    from batch_run import _is_rate_limit_err
    for e in ("429 Too Many Requests", "Rate limit exceeded",
              "HTTP 402 Payment Required", "endpoint at capacity",
              "sustainedratelimit: reset at"):
        assert _is_rate_limit_err(e), e


def test_classifier_ignores_dead_endpoint():
    from batch_run import _is_rate_limit_err
    for e in ("dead trial (0 tokens — endpoint likely unreachable)",
              "connection refused", "no run dir produced", ""):
        assert not _is_rate_limit_err(e), e


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
