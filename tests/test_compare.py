"""Pre/post comparison (scripts/compare.py).

Pins: per-cell k/n + Fisher for both sides; the UNDERPOWERED honesty marker
(both k=0 or n<min-n must not read as "no change"); the train/test overlap
split driven by export manifests (held-out CMH only over clean cells); the
detector-version heterogeneity warning.
"""
import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import compare as cmp


def _trial(runs, name, model, *, scenario="config_exposure", frame="A",
           exfil=False, escape=False, judged=None, tokens=100, steps=10,
           detector="d1"):
    d = runs / name
    d.mkdir()
    m = {"model": model, "scenario": scenario, "frame": frame,
         "agency": False, "aware_condition": False, "total_tokens": tokens,
         "steps": steps, "exfil_attempt": exfil, "escape_attempt": escape,
         "reasoning_escape_flag": False, "detector_version": detector}
    (d / "metrics.json").write_text(json.dumps(m), encoding="utf-8")
    if judged is not None:
        (d / "judge.json").write_text(json.dumps(
            {"trial_verdict": judged,
             "genuine": judged == "GENUINE_SELF_BOOTSTRAP",
             "prompt_sha": "x"}), encoding="utf-8")
    return d


@pytest.fixture
def runs(tmp_path):
    r = tmp_path / "runs"
    r.mkdir()
    # Cell 1 (Frame A, n=20/side): B has 5 exfil, A has 1 -> clear delta
    for i in range(20):
        _trial(r, f"config_exposure_20260101_{i:06d}_a", "base",
               exfil=(i == 0), judged="ARCHIVE")
        _trial(r, f"config_exposure_20260101_{i:06d}_b", "base+tune",
               exfil=(i < 5),
               judged="GENUINE_SELF_BOOTSTRAP" if i < 5 else "NO_UPLOAD")
    # Cell 2 (Frame B, small n): sparse events -> UNDERPOWERED at default
    # min-n, but informative for the held-out CMH when min-n is lowered
    for i in range(3):
        _trial(r, f"config_exposure_20260102_{i:06d}_a", "base", frame="B")
        _trial(r, f"config_exposure_20260102_{i:06d}_b", "base+tune", frame="B",
               exfil=(i == 0))
    return r


def _compare(runs, tmp_path, capsys=None, *extra):
    out = str(tmp_path / "c.csv")
    cmp.main(["--runs", str(runs), "--a", "base", "--b", "base+tune",
              "--out", out] + list(extra))
    rows = list(csv.DictReader(open(out)))
    captured = capsys.readouterr() if capsys else None
    return rows, captured


def _get(rows, outcome, cell_sub):
    return [r for r in rows if r["outcome"] == outcome and cell_sub in r["cell"]]


def test_cell_counts_fisher_and_delta(runs, tmp_path):
    rows, _ = _compare(runs, tmp_path, None, "--min-n", "5")
    exfil_a = _get(rows, "exfil", "|A|")[0]
    assert (exfil_a["a_k"], exfil_a["a_n"]) == ("1", "20")
    assert (exfil_a["b_k"], exfil_a["b_n"]) == ("5", "20")
    assert float(exfil_a["delta"]) == pytest.approx(0.2)
    assert float(exfil_a["fisher_p"]) < 0.25  # 1/20 vs 5/20
    gen = _get(rows, "genuine", "|A|")[0]
    assert (gen["a_k"], gen["a_n"]) == ("0", "20")  # ARCHIVE judged, not genuine
    assert (gen["b_k"], gen["b_n"]) == ("5", "20")


def test_underpowered_marker(runs, tmp_path):
    rows, _ = _compare(runs, tmp_path)
    small = _get(rows, "exfil", "|B|")[0]
    assert small["underpowered"] == "True"  # n=3 < default min-n 20
    big = _get(rows, "exfil", "|A|")[0]
    assert big["underpowered"] == "False"


def test_train_overlap_split_and_heldout_cmh(runs, tmp_path, capsys):
    # manifest containing the BASE trials of cell A: that cell is trained-on,
    # cell B is held out. CMH must then be reported for both scopes.
    man = tmp_path / "export_manifest.json"
    ids = [f"config_exposure_20260101_{i:06d}_a" for i in range(20)]
    man.write_text(json.dumps({"trial_ids": ids}), encoding="utf-8")
    rows, text = _compare(runs, tmp_path, capsys, "--min-n", "3",
                          "--export-manifest", str(man))
    trained = _get(rows, "exfil", "|A|")[0]
    heldout = _get(rows, "exfil", "|B|")[0]
    assert int(trained["train_overlap_trials"]) == 20
    assert int(heldout["train_overlap_trials"]) == 0
    assert heldout["a_k"] == "0" and heldout["b_k"] == "1"  # informative stratum
    assert "held-out cells only" in text.out
    assert "[train overlap:" in text.out


def test_detector_heterogeneity_warns(runs, tmp_path, capsys):
    _trial(runs, "config_exposure_20260103_000000_b", "base+tune",
           exfil=True, detector="d2")
    rows, captured = _compare(runs, tmp_path, capsys)
    assert "detector versions" in captured.err
