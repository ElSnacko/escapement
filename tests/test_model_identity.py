"""Tests for core/model_identity.py::extract_source.

Locks the source/publisher-org extraction so the exact model artifact stays
identifiable (model + model_label + source). The rule: extract only from a
genuine 'org/name' id; never guess for bare ids or file paths.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.model_identity import extract_source


def test_org_name_id():
    assert extract_source("unsloth/Qwen3.6-35B-A3B") == "unsloth"
    assert extract_source("google/gemma-4-31b-it:free") == "google"
    assert extract_source("nvidia/nemotron-3-nano-30b-a3b:free") == "nvidia"
    assert extract_source("meta-llama/llama-3.3-70b") == "meta-llama"


def test_bare_id_no_guess():
    # no slash -> no org; the operator asserts via --source.
    assert extract_source("gemma-4-31b") is None
    assert extract_source("deepseek-v4-flash") is None
    assert extract_source("deepseek-v4-flash-0731") is None


def test_filesystem_path_not_an_org():
    # leading slash or multiple slashes -> a path, not an org/name id.
    assert extract_source("/app/models/unsloth/Qwen3.6-35B-A3B-UD-Q5_K_XL.gguf") is None
    assert extract_source("some/dir/model.gguf") is None


def test_empty_and_none():
    assert extract_source("") is None
    assert extract_source(None) is None


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in tests:
        try:
            fn(); print(f"PASS  {fn.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}"); failed += 1
        except Exception:
            print(f"ERROR {fn.__name__}"); import traceback; traceback.print_exc(); failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
