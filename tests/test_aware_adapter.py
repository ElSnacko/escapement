"""Tests for the eval-awareness MANIPULATION adapter (--aware).

The observed `eval_awareness_flag` is correlational (a keyword heuristic over the
model's reasoning). `--aware` is the causal counterpart: it prepends an evaluation
notice to the system prompt so awareness becomes a randomized condition crossable
with any --frame, recorded as `aware_condition`. These tests validate the wiring
(no model needed): the flag parses, the snippet is a clean manipulation (states
the fact, does not instruct behaviour), and the batch axis threads through.

Run:  python tests/test_aware_adapter.py      (or: pytest tests/)
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import parse_args


def test_aware_flag_parses_and_defaults_off():
    assert parse_args(["--scenario", "config_exposure"]).aware is False
    assert parse_args(["--scenario", "config_exposure", "--aware"]).aware is True


def test_aware_is_orthogonal_to_frame():
    a = parse_args(["--scenario", "config_exposure", "--frame", "E", "--aware"])
    assert a.aware is True and a.frame == "E"


def test_awareness_snippet_is_a_clean_manipulation():
    import run
    snip = run._AWARENESS_SNIPPET.lower()
    # it must establish evaluation-awareness ...
    assert "evaluation" in snip and ("logged" in snip or "reviewed" in snip)
    # ... and PREPEND (frame the whole session), not append
    assert (run._AWARENESS_SNIPPET + "SYS").startswith("Note:")
    # ... but must NOT instruct behaviour, or it confounds awareness with a
    # safety directive (the manipulation would no longer be clean)
    for directive in ("should", "safely", "do not upload", "must not", "comply",
                      "refuse", "be careful"):
        assert directive not in snip, f"snippet leaks a behaviour directive: {directive}"


def test_batch_threads_the_aware_axis():
    import batch_run
    assert "aware=off" in batch_run._cell_label("s", "E", False, False)
    assert "aware=on" in batch_run._cell_label("s", "E", False, True)
    import inspect
    # both resume-count and the trial runner must accept the aware axis
    assert "aware" in inspect.signature(batch_run._count_valid_runs).parameters
    assert "aware" in inspect.signature(batch_run._trial).parameters


def _main():
    tests = [(n, v) for n, v in sorted(globals().items())
             if n.startswith("test_") and callable(v)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL  {name}: {exc}")
            failed += 1
        except Exception:
            print(f"ERROR {name}:")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
