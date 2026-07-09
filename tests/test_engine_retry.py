"""Engine retry tests: _post must retry transport errors (connection resets /
dropped streams), not just 429/5xx. Free-tier endpoints reset constantly;
without transport retry ~78% of trials die on the first dropped connection.

Run:  python tests/test_engine_retry.py   (or: pytest tests/)
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from core.engine import InferenceEngine
import core.engine as engine_mod


class _FakeResp:
    def __init__(self, status=200):
        self.status_code = status
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}")

    def close(self):
        pass


def _no_sleep():
    real = engine_mod.time.sleep
    engine_mod.time.sleep = lambda s: None
    return real


def test_post_retries_connection_reset_then_succeeds():
    eng = InferenceEngine(host="http://x", model="m", max_retries=3)
    state = {"n": 0}

    def fake_post(*a, **k):
        state["n"] += 1
        if state["n"] < 3:
            raise requests.exceptions.ConnectionError("ConnectionResetError(10054)")
        return _FakeResp(200)

    eng.session.post = fake_post
    real_sleep = _no_sleep()
    try:
        resp = eng._post("http://x/v1/chat/completions", {})
    finally:
        engine_mod.time.sleep = real_sleep
    assert state["n"] == 3, f"should retry twice then succeed (got {state['n']} calls)"
    assert resp.status_code == 200


def test_post_retries_chunked_encoding_then_succeeds():
    eng = InferenceEngine(host="http://x", model="m", max_retries=4)
    state = {"n": 0}

    def fake_post(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise requests.exceptions.ChunkedEncodingError("broken")
        return _FakeResp(200)

    eng.session.post = fake_post
    real_sleep = _no_sleep()
    try:
        resp = eng._post("http://x/v1/chat/completions", {})
    finally:
        engine_mod.time.sleep = real_sleep
    assert state["n"] == 2, "one drop then success"
    assert resp.status_code == 200


def test_post_raises_after_max_transport_retries():
    eng = InferenceEngine(host="http://x", model="m", max_retries=2)
    state = {"n": 0}

    def fake_post(*a, **k):
        state["n"] += 1
        raise requests.exceptions.ConnectionError("reset")

    eng.session.post = fake_post
    real_sleep = _no_sleep()
    try:
        try:
            eng._post("http://x/v1/chat/completions", {})
            assert False, "should have raised after exhausting retries"
        except requests.exceptions.ConnectionError:
            pass
    finally:
        engine_mod.time.sleep = real_sleep
    assert state["n"] == 3, f"max_retries=2 -> 3 attempts then re-raise (got {state['n']})"


def test_post_does_not_retry_4xx():
    eng = InferenceEngine(host="http://x", model="m", max_retries=4)
    state = {"n": 0}

    def fake_post(*a, **k):
        state["n"] += 1
        return _FakeResp(400)

    eng.session.post = fake_post
    real_sleep = _no_sleep()
    try:
        try:
            eng._post("http://x/v1/chat/completions", {})
            assert False, "400 should raise"
        except requests.exceptions.HTTPError:
            pass
    finally:
        engine_mod.time.sleep = real_sleep
    assert state["n"] == 1, "4xx must not retry"


def _main():
    tests = [(n, v) for n, v in sorted(globals().items())
             if n.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS  " + name)
        except Exception:
            print("FAIL  " + name)
            traceback.print_exc()
            failed += 1
    print(f"\n{len(tests) - failed} passed, {failed} failed, {len(tests)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
