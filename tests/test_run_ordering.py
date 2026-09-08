"""S2: run.main ordering -- refusal paths cost nothing and leave no orphans.

Pins the reordered main():
  * scenario load + the pure Frame E applicability check run BEFORE the
    endpoint health check and BEFORE the sandbox reset/seed/clear, so an
    inapplicable frame returns exit 4 with zero side effects (no engine
    round-trip, no workspace mutation, no run dir);
  * run dir + logger are created only after every refusal path, so exit 2/3/4
    leave no orphan directory in --log-dir.

The sandbox reset itself STAYS in its original position relative to the
engine/agency/injection steps; only the scenario/applicability check moved
earlier and the run-dir/logger creation moved later.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run
from core.engine import InferenceEngine
from core.sandbox import Sandbox


def _boom(name):
    def f(*a, **kw):
        raise AssertionError(f"{name} reached -- must not run before the "
                             f"Frame E applicability refusal")
    return f


def test_frame_e_refusal_precedes_endpoint_and_sandbox(monkeypatch, tmp_path):
    hits = []

    def health(self):
        hits.append("health")
        raise AssertionError("engine health reached before Frame E refusal")

    def reset(self):
        hits.append("reset")
        raise AssertionError("sandbox reset reached before Frame E refusal")

    monkeypatch.setattr(InferenceEngine, "health", health)
    monkeypatch.setattr(Sandbox, "reset_workspace", reset)
    rc = run.main(["--scenario", "goal_preservation_noupload", "--frame", "E",
                   "--host", "http://127.0.0.1:1",
                   "--log-dir", str(tmp_path)])
    assert rc == 4
    assert hits == [], "neither the endpoint nor the sandbox may be touched"
    assert list(tmp_path.iterdir()) == [], "refusal must not create a run dir"


def test_exit2_creates_no_run_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(InferenceEngine, "health", lambda self: False)
    monkeypatch.setattr(Sandbox, "reset_workspace", _boom("reset"))
    rc = run.main(["--scenario", "goal_preservation_noupload", "--frame", "A",
                   "--host", "http://127.0.0.1:1",
                   "--log-dir", str(tmp_path)])
    assert rc == 2
    assert list(tmp_path.iterdir()) == [], "exit 2 must not create a run dir"


def test_frame_e_on_upload_scenario_proceeds(monkeypatch, tmp_path):
    # config_exposure DOES instruct an upload -> the applicability check must
    # pass and the run proceed at least to the (failing) health check.
    monkeypatch.setattr(InferenceEngine, "health", lambda self: False)
    monkeypatch.setattr(Sandbox, "reset_workspace", _boom("reset"))
    rc = run.main(["--scenario", "config_exposure", "--frame", "E",
                   "--host", "http://127.0.0.1:1",
                   "--log-dir", str(tmp_path)])
    assert rc == 2, "applicable Frame E must not be refused (exit 4)"
    assert list(tmp_path.iterdir()) == []
