"""S10: the shared corpus iterator + validity predicate.

Pins: every exclusion class of is_valid_trial; iter_trials skipping debris;
read_json never raising; and -- the reason this module exists -- agreement
between the predicate and batch_run._scan_runs counting on the SAME fixture
set (the two must never disagree about n again).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import batch_run
from core.corpus import is_valid_trial, iter_trials, read_json


def _write(runs, name, **fields):
    d = runs / name
    d.mkdir()
    m = {"scenario": "config_exposure", "frame": "A", "agency": False,
         "aware_condition": False, "model": "test-model", "total_tokens": 100,
         "steps": 10, "degenerated": False, "escape_attempt": False,
         "exfil_attempt": False, "reasoning_escape_flag": False}
    m.update(fields)
    (d / "metrics.json").write_text(json.dumps(m), encoding="utf-8")


def test_validity_predicate_exclusions(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write(runs, "a1")                                   # valid
    _write(runs, "a2", total_tokens=0)                   # dead endpoint
    _write(runs, "a3", steps=2)                          # too short
    _write(runs, "a4", degenerated=True)                 # generation loop
    _write(runs, "a5", engine_error="boom")              # engine-killed (S7+)
    got = {n: is_valid_trial(m) for n, _, m in iter_trials(str(runs))}
    assert got == {"a1": True, "a2": False, "a3": False,
                   "a4": False, "a5": False}
    # legacy trials carry no engine_error field: unaffected
    _write(runs, "a6")
    m6 = json.loads((runs / "a6" / "metrics.json").read_text(encoding="utf-8"))
    m6.pop("engine_error", None)
    (runs / "a6" / "metrics.json").write_text(json.dumps(m6), encoding="utf-8")
    assert is_valid_trial(m6) is True


def test_iter_trials_skips_debris(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write(runs, "good_1")
    (runs / "no_metrics").mkdir()                        # dir without metrics
    (runs / "bad_json").mkdir()
    (runs / "bad_json" / "metrics.json").write_text("{", encoding="utf-8")
    (runs / "stray.json").write_text("{}", encoding="utf-8")   # not a dir
    names = [n for n, _, _ in iter_trials(str(runs))]
    assert names == ["good_1"]
    assert list(iter_trials(str(tmp_path / "nonexistent"))) == []


def test_read_json_never_raises(tmp_path):
    p = tmp_path / "x.json"
    assert read_json(str(p), default={"d": 1}) == {"d": 1}   # absent
    p.write_text("{not json", encoding="utf-8")
    assert read_json(str(p), default=[]) == []               # unparseable
    p.write_text('{"k": "—\U0001F680"}', encoding="utf-8")
    assert read_json(str(p))["k"] == "—\U0001F680"           # utf-8 round trip


def test_scan_runs_agrees_with_predicate(tmp_path):
    # THE point of S10: the batch fill counter and the predicate must agree
    # on the same fixtures (four walkers already excluded degenerated;
    # batch now shares the one definition, plus engine_error).
    runs = tmp_path / "runs"
    runs.mkdir()
    _write(runs, "config_exposure_1", exfil_attempt=True)          # valid
    _write(runs, "config_exposure_2")                              # valid
    _write(runs, "config_exposure_3", total_tokens=0)              # dead
    _write(runs, "config_exposure_4", steps=1)                     # short
    _write(runs, "config_exposure_5", degenerated=True)            # degenerate
    _write(runs, "config_exposure_6", engine_error="boom")         # engine-killed
    _write(runs, "config_exposure_7", frame="B")                   # other cell
    stats = batch_run._scan_runs([("config_exposure", "A", False, False),
                                  ("config_exposure", "B", False, False)],
                                 model_filter="test-model", runs_dir=str(runs))
    a, b = stats
    assert a["n"] == 2 and a["kx"] == 1
    assert a["kd"] == 1                 # the degenerate trial is countable QC
    assert b["n"] == 1
    # direct agreement: predicate count == scan count over the same corpus
    valid = sum(1 for _, _, m in iter_trials(str(runs)) if is_valid_trial(m)
                and m["frame"] == "A" and m["model"] == "test-model")
    assert valid == a["n"]
