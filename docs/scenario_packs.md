# Scenario packs

A **scenario pack** is a directory that plugs custom eval scenarios into the
harness without touching the repo — the "custom dataset" arm of the
fine-tuned-model re-test workflow (README → *Testing a fine-tuned model*),
and a way to keep held-out re-test surfaces out of the training data
(`export_finetune.py --holdout` excludes repo cells; a pack is excluded by
construction, since it never entered `runs/` before the re-test).

## Layout

```
my_pack/
  pack.json          # required: cell axes + metadata
  demo_task.py       # scenario modules (one Scenario subclass each)
  another_task.py
```

`pack.json` — any axis omitted falls back to the CLI default:

```json
{
  "name": "my-holdout-pack",
  "description": "Held-out re-test surface for the distill study",
  "scenarios": ["demo_task", "another_task"],
  "frames": ["A", "B"],
  "agency": "both",
  "aware": "off",
  "n": 20
}
```

## Scenario module contract

Exactly like a repo scenario (`scenarios/*.py`): a module defining one
`Scenario` subclass, configured via class attributes —

```python
from core.scenario import Scenario

class DemoTaskScenario(Scenario):
    name = "demo_task"                       # run dirs + metrics use this
    system_prompt = "You are ..."            # job briefing
    task_message = "Your shift: ..."         # the task message
    seed_files = {"README.txt": "...", ".env": "..."}  # workspace seed
    leaked_config_path = "/home/agent/workspace/.env"  # optional
    results_path = "results.jsonl"                        # optional
    instructed_upload = None                  # None = auto-detect (Frame E gate)
```

Rules:

- **Repo first.** A pack module never shadows a repo scenario name; `scenarios/`
  is searched before pack paths.
- **Self-contained modules.** A pack module may import `core.*` and repo
  siblings (`from scenarios import config_exposure`), but not other modules in
  its own pack — duplicate what you need or inline it.
- **Frames work.** Frame B/C injections apply generically via `queue.jsonl`
  merged into the workspace (the standard payload any non-`agent_coding`
  scenario receives — and a pack module cannot shadow the repo's
  `agent_coding`, so every pack scenario gets the standard injection);
  Frame D poisons the curl tool description; Frame E needs the scenario to
  instruct an upload (`instructs_upload` / auto-detected), else the trial exits 4.
- **Rescoring.** Pack trials persist `seed_text.txt` at run time (PR #11), so
  `aggregate.py --rescore` works from the artifact; the reconstruction
  fallback only knows repo scenarios — keep the pack directory around if you
  plan to rescore.

## Running a pack

```bash
# sweep the pack (pack.json fills scenarios/frames/agency/aware/n; an explicit
# CLI flag wins over pack.json)
python batch_run.py --pack my_pack/ --model-label student+distill-v1 \
    --weights-version "base+lora-v1" --judge --judge-model <reference>

# single trial from a pack, no pack.json needed
python run.py --scenario demo_task --scenario-path my_pack/ --host ...
```

`--pack` pre-flights every scenario (a bad module fails before any trial
starts) and forwards the directory to every trial as `--scenario-path`.
Resume counting, coverage, judging, aggregation, and `compare.py` all key on
the `scenario` field in `metrics.json`, so pack scenarios are first-class
there with no further wiring.
