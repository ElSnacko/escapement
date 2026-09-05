"""Fine-tuned-variant provenance: weights_version / precision / serving_stack.

A re-test of a fine-tuned model must be self-describing — which exact weights,
what precision, which serving stack — instead of encoding it in the
--model-label string. These pin the flow CLI -> metrics.json -> per_trial.csv
-> rescore (the rescore half matters: PR #11 fixed aware_condition being
dropped there; variant fields must not repeat that class of bug).
"""
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from core.config import parse_args


def test_variant_flags_parse_cli_and_env(monkeypatch):
    monkeypatch.setenv("ESCAPE_WEIGHTS_VERSION", "env-weights")
    ns = parse_args(["--scenario", "config_exposure"])
    assert ns.weights_version == "env-weights"
    assert ns.precision == "" and ns.serving_stack == ""
    ns = parse_args(["--scenario", "config_exposure",
                     "--weights-version", "base+lora-v1",
                     "--precision", "bf16",
                     "--serving-stack", "vLLM 0.10.0"])
    assert ns.weights_version == "base+lora-v1"
    assert ns.precision == "bf16"
    assert ns.serving_stack == "vLLM 0.10.0"


def test_run_persists_variant_fields_into_metrics():
    # Pin the metrics assembly without a live endpoint/sandbox (same style as
    # test_run_writes_seed_text_artifact).
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "run.py"), encoding="utf-8").read()
    for f in ("weights_version", "precision", "serving_stack"):
        assert f'metrics["{f}"] = args.{f}' in src


def test_batch_exposes_flags_and_forwards_via_passthrough():
    # The flags exist on batch_run's parser and ride the same extra_argv
    # passthrough as the judge set (smoke included), rather than growing
    # _trial's signature.
    import batch_run
    src = inspect.getsource(batch_run)
    for flag in ("--weights-version", "--precision", "--serving-stack"):
        assert f'"{flag}"' in src
    assert "judge_argv + variant_argv" in src


def test_trial_forwards_variant_argv(tmp_path, monkeypatch):
    # End-to-end through _trial with run.main monkeypatched: the flags must
    # arrive in run.py's argv and the trial must still resolve its run dir.
    import batch_run
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    captured = {}

    def fake_run_one(argv):
        captured["argv"] = list(argv)
        d = tmp_path / "runs" / "config_exposure_20260101_000000_wv1x"
        d.mkdir()
        (d / "metrics.json").write_text(json.dumps(
            {"model": "m", "total_tokens": 10, "steps": 5}), encoding="utf-8")

    monkeypatch.setattr(batch_run, "run_one", fake_run_one)
    m, err = batch_run._trial("config_exposure", "A", False, False,
                              "http://localhost:8080", "not-needed", "native",
                              0.7, 30, 2048, tag="wv1x",
                              extra_argv=["--weights-version", "base+lora-v1",
                                          "--precision", "bf16",
                                          "--serving-stack", "vLLM 0.10.0"])
    assert err is None and m is not None
    argv = captured["argv"]

    def _val(flag):
        return argv[argv.index(flag) + 1]

    assert _val("--weights-version") == "base+lora-v1"
    assert _val("--precision") == "bf16"
    assert _val("--serving-stack") == "vLLM 0.10.0"


def test_flatten_carries_variant_columns():
    from aggregate import _flatten
    m = {"model": "gemma-4-31b", "source": "google",
         "weights_version": "base+lora-v1", "precision": "bf16",
         "serving_stack": "vLLM 0.10.0", "scenario": "config_exposure"}
    row = _flatten(m, "t1")
    assert row["weights_version"] == "base+lora-v1"
    assert row["precision"] == "bf16"
    assert row["serving_stack"] == "vLLM 0.10.0"
    # blank, not None, for stock weights (CSV column consistency)
    row = _flatten({"model": "gemma-4-31b", "scenario": "config_exposure"}, "t2")
    assert row["weights_version"] == "" and row["precision"] == ""
    assert row["serving_stack"] == ""


def test_rescore_preserves_variant_fields(tmp_path):
    # Same class of bug PR #11 fixed for aware_condition: _rescore rebuilds the
    # metrics dict from artifacts and must carry provenance from the stored one.
    from aggregate import _rescore
    d = tmp_path / "config_exposure_20260101_000009"
    d.mkdir()
    om = {"scenario": "config_exposure", "frame": "A", "model": "m",
          "weights_version": "base+lora-v1", "precision": "bf16",
          "serving_stack": "vLLM 0.10.0", "status": "finished",
          "steps": 5, "total_tokens": 100}
    (d / "metrics.json").write_text(json.dumps(om), encoding="utf-8")
    m = _rescore(str(d), {})
    assert m["weights_version"] == "base+lora-v1"
    assert m["precision"] == "bf16"
    assert m["serving_stack"] == "vLLM 0.10.0"
