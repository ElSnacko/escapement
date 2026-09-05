"""Scenario packs: custom eval scenarios outside the repo.

Pins: the loader's path search + repo-first shadowing + namespaced module
loading; compose_seed_text on a pack scenario (generic Frame B injection);
batch_run's --pack axis application (pack.json fills defaults, an explicit
CLI flag wins); the per-trial --scenario-path forwarding; run.py accepting
--scenario-path.
"""
import inspect
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.scenario import compose_seed_text, load_scenario

PACK_SCENARIO = '''
from core.scenario import Scenario

class PackDemoScenario(Scenario):
    name = "pack_demo"
    system_prompt = "You are the pack demo agent."
    task_message = "Do the demo job."
    seed_files = {"README.txt": "demo workspace"}
    results_path = "results.jsonl"
'''


@pytest.fixture
def pack(tmp_path):
    d = tmp_path / "my_pack"
    d.mkdir()
    (d / "pack_demo.py").write_text(PACK_SCENARIO, encoding="utf-8")
    (d / "pack.json").write_text(json.dumps({
        "name": "test-pack",
        "scenarios": ["pack_demo"],
        "frames": ["A", "B"],
        "agency": "both",
        "aware": "off",
        "n": 7,
    }), encoding="utf-8")
    return d


def test_load_scenario_from_pack_path(pack):
    sc = load_scenario("pack_demo", paths=[str(pack)])
    assert sc.name == "pack_demo"
    assert sc.seed_files == {"README.txt": "demo workspace"}


def test_repo_scenario_shadows_pack(tmp_path):
    # a pack module with a repo name must NOT win
    d = tmp_path / "shadow_pack"
    d.mkdir()
    (d / "config_exposure.py").write_text(
        "from core.scenario import Scenario\n"
        "class Evil(Scenario):\n"
        "    name = 'SHADOWED'\n", encoding="utf-8")
    sc = load_scenario("config_exposure", paths=[str(d)])
    assert sc.name != "SHADOWED"


def test_missing_scenario_still_raises(pack, tmp_path):
    with pytest.raises(ImportError):
        load_scenario("nope", paths=[str(pack), str(tmp_path)])


def test_pack_scenario_gets_generic_injection(pack):
    seed_b = compose_seed_text(load_scenario("pack_demo", paths=[str(pack)]),
                               frame="B")
    seed_a = compose_seed_text(load_scenario("pack_demo", paths=[str(pack)]),
                               frame="A")
    # the standard queue.jsonl injection rides the Frame B seed
    assert "restorable snapshot of yourself" in seed_b
    assert "restorable snapshot of yourself" not in seed_a


def test_apply_pack_fills_defaults_and_explicit_wins(pack, capsys):
    import batch_run
    defaults = {"scenarios": "goal_preservation,goal_guarding,goal_capacity",
                "frames": "A", "agency": "off", "aware": "off", "n": 10}
    # operator left everything at defaults -> pack fills all axes
    args = SimpleNamespace(pack=str(pack), scenario_path=None, **defaults)
    batch_run._apply_pack(args, dict(defaults))
    assert args.scenarios == "pack_demo"
    assert args.frames == "A,B"
    assert args.agency == "both"
    assert args.aware == "off"
    assert args.n == 7
    # explicit CLI flag (differs from parser default) wins
    args = SimpleNamespace(pack=str(pack), scenario_path=None,
                           scenarios="pack_demo", frames="C", agency="both",
                           aware="off", n=7)
    batch_run._apply_pack(args, dict(defaults))
    assert args.frames == "C"
    assert "keeping explicit --frames=C" in capsys.readouterr().out


def test_apply_pack_missing_manifest_exits(tmp_path, capsys):
    import batch_run
    empty = tmp_path / "empty_pack"
    empty.mkdir()
    with pytest.raises(SystemExit):
        batch_run._apply_pack(SimpleNamespace(pack=str(empty)), {})


def test_run_accepts_scenario_path_flag():
    from core.config import parse_args
    ns = parse_args(["--scenario", "x", "--scenario-path", "/tmp/p1",
                     "--scenario-path", "/tmp/p2"])
    assert ns.scenario_path == ["/tmp/p1", "/tmp/p2"]


def test_run_passes_paths_to_loader():
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "run.py"), encoding="utf-8").read()
    assert "load_scenario(args.scenario, paths=args.scenario_path)" in src


def test_batch_pack_forwarded_and_preflighted():
    # --pack rides the per-trial passthrough and triggers the pre-flight load
    import batch_run
    src = inspect.getsource(batch_run)
    assert '["--scenario-path", args.pack]' in src
    assert "judge_argv + variant_argv + pack_argv" in src
    assert "pack scenario" in src  # pre-flight error message
