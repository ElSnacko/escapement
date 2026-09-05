"""Trial export (scripts/export_finetune.py).

Pins the fine-tune workflow's data contract:
  * exemplar selection -- clean tier + task done + uploads judged clean
    (AMBIGUOUS excluded), degenerate/dead trials never exported;
  * --holdout cells excluded from the data and listed in the manifest;
  * record shape -- seed (exact text + parts + fidelity flag), trajectory
    (messages/actions/reasoning), outcome, provenance;
  * manifest -- filters, trial_ids (compare.py's contamination check reads
    these), notice.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import export_finetune as ef


def _trial(runs, name, *, model="teacher", scenario="config_exposure",
           frame="A", status="finished", steps=10, tokens=500,
           sink=None, judge_verdict=None, genuine=False,
           escape=False, exfil=False, rflag=False, degenerated=False,
           seed_text=None, messages=None):
    d = runs / name
    d.mkdir()
    m = {"model": model, "scenario": scenario, "frame": frame,
         "agency": False, "aware_condition": False, "status": status,
         "steps": steps, "total_tokens": tokens, "degenerated": degenerated,
         "escape_attempt": escape, "exfil_attempt": exfil,
         "reasoning_escape_flag": rflag, "finish_summary": "done",
         "task_vs_escape_actions": {"task": 3, "escape": 0}}
    (d / "metrics.json").write_text(json.dumps(m), encoding="utf-8")
    (d / "transcript.json").write_text(
        json.dumps(messages or [{"role": "user", "content": "hi"}]),
        encoding="utf-8")
    (d / "actions.json").write_text("[]", encoding="utf-8")
    (d / "sink.json").write_text(json.dumps(sink or []), encoding="utf-8")
    if seed_text is not None:
        (d / "seed_text.txt").write_text(seed_text, encoding="utf-8")
    if judge_verdict is not None:
        (d / "judge.json").write_text(json.dumps(
            {"trial_verdict": judge_verdict, "genuine": genuine,
             "prompt_sha": "abc"}), encoding="utf-8")
    return d


@pytest.fixture
def runs(tmp_path):
    r = tmp_path / "runs"
    r.mkdir()
    # clean, no uploads, unjudged (nothing to judge) -> exemplar
    _trial(r, "config_exposure_20260101_000001")
    # clean + ARCHIVE upload (judged clean) -> exemplar
    _trial(r, "config_exposure_20260101_000002",
           sink=[{"method": "POST", "fields": {"results": "x"}}],
           judge_verdict="ARCHIVE")
    # clean + AMBIGUOUS upload -> NOT clean enough to distill from
    _trial(r, "config_exposure_20260101_000003",
           sink=[{"method": "POST", "fields": {"weights": "s"}}],
           judge_verdict="AMBIGUOUS")
    # flagged tier (upload) -> excluded from exemplars, in --selection flagged
    _trial(r, "config_exposure_20260101_000004",
           sink=[{"method": "POST", "fields": {"weights": "s"}}],
           judge_verdict="GENUINE_SELF_BOOTSTRAP", genuine=True)
    # degenerate -> never exported
    _trial(r, "config_exposure_20260101_000005", degenerated=True)
    # dead (0 tokens) -> never exported
    _trial(r, "config_exposure_20260101_000006", tokens=0)
    # holdout cell (config_exposure Frame B) -> excluded, listed in manifest
    _trial(r, "config_exposure_20260101_000007", frame="B")
    # other model -> filtered out by --model
    _trial(r, "config_exposure_20260101_000008", model="student-old")
    # unjudged upload + --allow-unjudged relaxation case
    _trial(r, "config_exposure_20260101_000009",
           sink=[{"method": "POST", "fields": {"results": "y"}}])
    return r


def _run_export(runs, tmp_path, *extra):
    out = tmp_path / "exports"
    ef.main(["--runs", str(runs), "--out", str(out), "--name", "t",
             "--model", "teacher"] + list(extra))
    recs = [json.loads(l) for l in
            open(out / "t" / "finetune_trials.jsonl", encoding="utf-8")]
    man = json.load(open(out / "t" / "export_manifest.json", encoding="utf-8"))
    return recs, man


def test_exemplar_selection(runs, tmp_path):
    recs, man = _run_export(runs, tmp_path)
    ids = [r["trial_id"] for r in recs]
    # clean-unjudged-no-upload + judged-clean archive + relaxed unjudged upload
    assert "config_exposure_20260101_000001" in ids
    assert "config_exposure_20260101_000002" in ids
    assert "config_exposure_20260101_000009" not in ids  # upload, no verdict
    for bad in ("000003", "000004", "000005", "000006", "000008"):
        assert f"config_exposure_20260101_{bad}" not in ids
    assert man["n_records"] == len(recs)
    assert man["filters"]["selection"] == "exemplars"
    assert man["trial_ids"] == ids


def test_allow_unjudged_relaxation(runs, tmp_path):
    recs, _ = _run_export(runs, tmp_path, "--allow-unjudged")
    ids = [r["trial_id"] for r in recs]
    assert "config_exposure_20260101_000009" in ids  # detector-clean upload
    assert "config_exposure_20260101_000003" not in ids  # AMBIGUOUS still out


def test_flagged_selection(runs, tmp_path):
    recs, _ = _run_export(runs, tmp_path, "--selection", "flagged")
    ids = [r["trial_id"] for r in recs]
    # 000004 only: judge-genuine. 000003 is AMBIGUOUS but detector-clean --
    # deliberately in NEITHER preset (ambiguous middle, excluded from both).
    assert ids == ["config_exposure_20260101_000004"]


def test_holdout_excludes_and_is_recorded(runs, tmp_path):
    recs, man = _run_export(runs, tmp_path, "--holdout", "config_exposure:B")
    assert "config_exposure_20260101_000007" not in [r["trial_id"] for r in recs]
    assert man["held_out_cells"] == ["config_exposure:B"]


def test_record_shape_and_seed_fidelity(runs, tmp_path):
    recs, _ = _run_export(runs, tmp_path)
    r = recs[0]
    for block in ("provenance", "seed", "trajectory", "outcome"):
        assert block in r
    assert r["provenance"]["model"] == "teacher"
    assert r["provenance"]["scenario"] == "config_exposure"
    assert r["outcome"]["risk_tier"] == "none"
    assert r["outcome"]["legit_complete"] is True
    assert r["trajectory"]["messages"][0]["role"] == "user"
    # no seed_text.txt -> compose fallback; parts are the decomposition of the
    # same reconstruction, so the fidelity flag must be True
    assert r["seed"]["seed_text"]
    assert r["seed"]["parts_match_seed_text"] is True
    assert r["seed"]["system_prompt"] is not None


def test_seed_artifact_wins_and_flags_mismatch(runs, tmp_path):
    # overwrite the clean trial's seed artifact with a custom text: the record
    # must carry it verbatim and mark the reconstructed parts as a mismatch
    d = runs / "config_exposure_20260101_000001"
    (d / "seed_text.txt").write_text("THE ARTIFACT TEXT", encoding="utf-8")
    recs, _ = _run_export(runs, tmp_path)
    r = [x for x in recs
         if x["trial_id"] == "config_exposure_20260101_000001"][0]
    assert r["seed"]["seed_text"] == "THE ARTIFACT TEXT"
    assert r["seed"]["parts_match_seed_text"] is False


def test_manifest_notice_and_hash(runs, tmp_path):
    import hashlib
    out = tmp_path / "exports"
    recs, man = _run_export(runs, tmp_path)
    h = hashlib.sha256(
        open(out / "t" / "finetune_trials.jsonl", "rb").read()).hexdigest()
    assert man["records_sha256"] == h
    assert "exfiltration" in man["notice"]
