"""S11 small fixes with observable behavior: --seed wiring (C1) and the
max_tokens-scaled read timeout (B3 option 1).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent import Agent
from core.engine import InferenceEngine


class _Rec:
    """Engine stub recording the kwargs of each turn call."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.kwargs = []

    def chat_with_tools(self, messages, tools, **kw):
        self.kwargs.append(kw)
        return self.turns.pop(0)


def _finish_turn():
    return {"message": {"content": "done", "tool_calls": [
        {"id": "c1", "name": "finish", "arguments": {"summary": "s"}}]},
        "usage": {}, "reasoning": "", "timings": {}}


def test_seed_zero_omitted_nonzero_forwarded():
    # seed=0 (the default) must NOT add a key: the corpus sampling regime is
    # byte-identical to pre-S11 requests. A nonzero seed rides the payload.
    eng = _Rec([_finish_turn()])
    Agent(eng, None, seed=0).run("s", "t")
    assert "seed" not in eng.kwargs[0]

    eng = _Rec([_finish_turn()])
    Agent(eng, None, seed=42).run("s", "t")
    assert eng.kwargs[0].get("seed") == 42


def test_timeout_scales_with_max_tokens(monkeypatch):
    # A non-streaming server sends nothing until the whole completion is
    # done; requests' read timeout counts silent time, so a healthy 4096-token
    # generation on a slow endpoint timed out and the retry REGENERATED it.
    # The effective timeout must grow with the token budget (>= max_tokens/8
    # seconds, ~8 tok/s floor).
    eng = InferenceEngine("http://x", "m", timeout=120)
    seen = {}

    def fake_post(url, json_body=None, stream=False, timeout=None, **kw):
        seen["timeout"] = timeout
        raise RuntimeError("stop here")          # enough -- we only read kwargs

    monkeypatch.setattr(eng.session, "post", fake_post)
    try:
        eng.chat_with_tools([], [], max_tokens=4096)
    except RuntimeError:
        pass
    assert seen["timeout"] == max(120, 4096 // 8)   # 512

    try:
        eng.chat_with_tools([], [], max_tokens=512)
    except RuntimeError:
        pass
    assert seen["timeout"] == 120                   # unchanged under the floor


def test_default_host_resolves_after_load_env(tmp_path, monkeypatch):
    # Regression: a module-level DEFAULT_HOST constant was evaluated when
    # core.config was imported -- BEFORE load_env() runs in main() -- so an
    # ESCAPE_HOST line in .env (the documented per-session workflow in
    # .env.example) never reached the --host default. The default must be
    # resolved at parse time.
    from core import config as _config
    from core.env import load_env
    monkeypatch.delenv("ESCAPE_HOST", raising=False)
    assert _config.default_host() == _config.FALLBACK_HOST
    dotenv = tmp_path / ".env"
    dotenv.write_text("ESCAPE_HOST=http://from-dotenv:9999\n", encoding="utf-8")
    load_env(str(dotenv))          # explicit path: bypasses the once-only guard
    assert _config.default_host() == "http://from-dotenv:9999"
    ns = _config.parse_args(["--scenario", "config_exposure"])
    assert ns.host == "http://from-dotenv:9999"
    # and batch_run's parser uses the same call-time resolver
    import batch_run
    assert batch_run.default_host() == "http://from-dotenv:9999"
    src = open(batch_run.__file__, encoding="utf-8").read()
    assert 'default=default_host()' in src
    assert "DEFAULT_HOST" not in src
