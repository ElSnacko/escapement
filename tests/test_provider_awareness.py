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


def test_parse_x_ratelimit_reset_seconds_relative():
    # A small relative value (seconds-from-now) must NOT be divided by 1000.
    before = time.time()
    ts = _parse_reset_ts({"x-ratelimit-reset": "60"})
    after = time.time()
    assert ts is not None and before + 59 <= ts <= after + 61


def test_parse_x_ratelimit_reset_seconds_epoch():
    # A seconds-epoch value (~1.7e9) is returned as-is, not divided by 1000.
    target = time.time() + 600
    ts = _parse_reset_ts({"x-ratelimit-reset": str(int(target))})
    assert ts is not None and abs(ts - target) < 2


def test_local_host_high_concurrency():
    # Self-hosted servers (loopback / LAN) handle their own concurrency -- the
    # guard must not warn against them.
    assert max_concurrency_for("http://127.0.0.1:8000") > 1
    assert max_concurrency_for("http://localhost:8080") > 1
    assert max_concurrency_for("http://192.168.1.50:8000") > 1
    assert max_concurrency_for("http://10.0.0.5:8000") > 1
    assert provider_for("http://127.0.0.1:8000")["tier"] == "local"
    # A public unknown host still falls back to the conservative default.
    assert max_concurrency_for("https://never-heard-of.it") == 1


def test_parse_http_date():
    ts = _parse_reset_ts({"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"})
    assert ts is not None and ts > time.time()


def test_parse_none_when_absent():
    assert _parse_reset_ts({}) is None
    assert _parse_reset_ts({"Content-Type": "application/json"}) is None


def test_sustained_error_carries_reset():
    err = SustainedRateLimitError(reset_ts=123.0)
    assert err.reset_ts == 123.0


# --- S1: the exception must actually be constructible at its raise site -----
# The old constructor forwarded `message=` into requests.RequestException,
# whose IOError base rejects it -> the raise site itself raised TypeError,
# so every sustained-429 handling path (exit 5, RATE classifier, S9 parking)
# was dead code.

def test_sustained_error_message_positional():
    err = SustainedRateLimitError("429 rate limit; reset at 123", reset_ts=123.0)
    assert "429" in str(err)
    assert err.reset_ts == 123.0


def test_sustained_error_raised_through_post(monkeypatch):
    from core.engine import InferenceEngine
    eng = InferenceEngine("http://x", "m")
    calls = {"n": 0}

    class _Resp:
        status_code = 429
        headers = {"Retry-After": "3600"}  # > 5 min out => sustained

        def close(self):
            pass

    def fake_post(*a, **kw):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(eng.session, "post", fake_post)
    before = time.time()
    try:
        eng._post("http://x/v1/chat/completions", {})
    except TypeError:
        raise AssertionError("constructor TypeError: raise site is broken")
    except SustainedRateLimitError as exc:
        assert calls["n"] == 1, "must fail fast, no retry loop"
        assert exc.reset_ts is not None
        assert before + 3590 <= exc.reset_ts <= time.time() + 3605
        assert "429" in str(exc)
    else:
        raise AssertionError("expected SustainedRateLimitError")


def test_batch_classifies_sustained_error_from_post(monkeypatch):
    # The classifier (and the [RATE] path / S9 parking) reads the error STRING
    # of the exception _post raises -- the round trip must survive str().
    from batch_run import _is_rate_limit_err
    from core.engine import InferenceEngine
    eng = InferenceEngine("http://x", "m")

    class _Resp:
        status_code = 429
        headers = {"Retry-After": "3600"}

        def close(self):
            pass

    monkeypatch.setattr(eng.session, "post", lambda *a, **kw: _Resp())
    try:
        eng._post("http://x/v1/chat/completions", {})
    except SustainedRateLimitError as exc:
        assert _is_rate_limit_err(f"trial crashed: {exc}")
    else:
        raise AssertionError("expected SustainedRateLimitError")


# --- batch_run rate-limit classifier ----------------------------------------

def test_classifier_matches_throttling():
    from batch_run import _is_rate_limit_err
    for e in ("429 Too Many Requests", "Rate limit exceeded",
              "endpoint at capacity", "sustainedratelimit: reset at",
              "quota exceeded"):
        assert _is_rate_limit_err(e), e


def test_classifier_treats_payment_as_permanent():
    # 402 / out-of-credit is permanent (won't recover this session) -> NOT
    # classified as transient, so it still counts toward the dead-endpoint abort.
    from batch_run import _is_rate_limit_err
    for e in ("HTTP 402 Payment Required", "insufficient credit",
              "billing: no credit remaining"):
        assert not _is_rate_limit_err(e), e


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
