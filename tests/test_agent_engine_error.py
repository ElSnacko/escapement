"""S7: engine errors mid-trial are distinguishable from a benign stop.

Agent.run ends a trial on any engine exception with the same ``status:
"stopped"`` as a model that simply answered in text; only trace.jsonl knew
the difference. The result dict (and metrics.json via compute_metrics) must
carry the error string so downstream validity/walkers can see it (S10) and
batch accounting can surface it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent import Agent
from core.capture import compute_metrics


def _finish_turn(summary="s"):
    return {"message": {"content": "done", "tool_calls": [
        {"id": "c1", "name": "finish", "arguments": {"summary": summary}}]},
        "usage": {"prompt_tokens": 5, "completion_tokens": 5},
        "reasoning": "", "timings": {}}


def test_engine_exception_recorded_status_unchanged():
    class Boom:
        def chat_with_tools(self, *a, **kw):
            raise RuntimeError("boom")

    ag = Agent(Boom(), None, max_steps=5)
    res = ag.run("sys", "task")
    assert res["status"] == "stopped"          # status semantics unchanged
    assert res["engine_error"] == "boom"


def test_non_dict_turn_recorded():
    class Weird:
        def chat_with_tools(self, *a, **kw):
            return None                         # non-dict turn (gateway bug)

    ag = Agent(Weird(), None, max_steps=5)
    res = ag.run("sys", "task")
    assert res["status"] == "stopped"
    assert res["engine_error"] and "NoneType" in res["engine_error"]


def test_normal_finish_has_no_engine_error():
    class Ok:
        def __init__(self):
            self.n = 0

        def chat_with_tools(self, *a, **kw):
            return _finish_turn()

    ag = Agent(Ok(), None, max_steps=5)
    res = ag.run("sys", "task")
    assert res["status"] == "finished"
    assert res["engine_error"] is None


def test_compute_metrics_carries_engine_error():
    res = {"actions": [], "scratchpad": [], "reasoning": [], "steps": 3,
           "status": "stopped", "engine_error": "boom"}
    m = compute_metrics(res, [], {}, {"name": "x"}, seed_text="")
    assert m["engine_error"] == "boom"
    # and absent for a clean run (legacy trials lack the field entirely)
    res.pop("engine_error")
    m2 = compute_metrics(res, [], {}, {"name": "x"}, seed_text="")
    assert "engine_error" in m2 and m2["engine_error"] is None
