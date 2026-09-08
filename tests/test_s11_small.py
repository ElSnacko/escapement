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
