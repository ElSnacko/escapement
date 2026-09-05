#!/usr/bin/env python3
"""Export harness trials as fine-tune-ready trajectory JSONL.

The fine-tuned-model workflow: run a well-behaved TEACHER through the harness,
export its clean trajectories here, distill a student externally (training is
deliberately out of repo), then re-test the student on the same frames or a
held-out pack and compare (scripts/compare.py).

  python scripts/export_finetune.py --model gemma-4-31b \
      --selection exemplars --holdout "config_exposure:B" --name teacher-v1

One JSON record per trial, format-neutral (slice into SFT/DPO/whatever the
external trainer wants):

  provenance   model/source/weights_version/... (the aggregate row identity)
  seed         seed_text (EXACT text the model was handed: artifact preferred,
               compose_seed_text fallback), plus system_prompt/task_message/
               seed_files parts with a parts_match fidelity flag
  trajectory   messages (transcript.json), actions, reasoning, scratchpad,
               sink records, dropped tool calls, finish summary
  outcome      risk_tier + all detector flags + legit_complete + judge verdict

Selection presets (the distillation default is positive exemplars from the
teacher, not its failures):
  exemplars   risk_tier=none AND legit_complete AND judged clean on any upload
              (verdict NO_UPLOAD/ARCHIVE; AMBIGUOUS is not clean enough to
              distill from). --allow-unjudged relaxes to detector-only clean
              -- the devstral 15(detector)->5(judge) split is why it shouldn't.
  flagged     reasoning/attempt/upload tier or judge-genuine (for analysis or
              remedation-adjacent datasets).
  all         no outcome filter.

Contamination control: --holdout "scenario:frame,scenario:frame" excludes those
cells from the export and lists them in the manifest, so the student's re-test
surface can be guaranteed absent from its training set. compare.py reads the
manifest's trial_ids to flag residual train/test overlap.

Responsible use (README): this data exists for safety evaluation, remediation,
and distillation of SAFE behavior. Do not train models toward exfiltration or
scheming with it.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.scenario import (AGENCY_SNIPPET, AWARENESS_SNIPPET,  # noqa: E402
                           compose_seed_text, load_scenario)
# aggregate's helpers are the canonical row shape (identity + derived outcome
# columns) -- reuse rather than re-derive, so export and analysis can't drift.
from aggregate import (_flatten, _git_sha, _judge_cols,  # noqa: E402
                       _seed_text_for)

# Judged-clean verdicts for --selection exemplars: the trial may UPLOAD (an
# ARCHIVE is correct task behavior worth distilling) but must not be a
# judge-confirmed or ambiguous self-bootstrap.
_CLEAN_VERDICTS = ("NO_UPLOAD", "ARCHIVE")


def _load_json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def _load_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _seed_parts(sc, frame, agency, aware):
    """The seed COMPONENTS run.py handed the model (mirrors compose_seed_text,
    which run-time mutation order equals; kept beside it so a trainer gets
    system/task/files instead of one opaque blob)."""
    seed_files = dict(sc.seed_files or {})
    if frame in ("B", "C"):
        from scenarios._injection import injection_for
        inj, _label = injection_for(sc.name, frame)
        if inj:
            seed_files = {**seed_files, **inj}
    system = sc.system_prompt or ""
    if agency:
        system = system + AGENCY_SNIPPET
    if aware:
        system = AWARENESS_SNIPPET + system
    return {"seed_files": seed_files, "system_prompt": system,
            "task_message": sc.task_message or ""}


def _scenario_for(name, cache):
    if name not in cache:
        try:
            cache[name] = load_scenario(name)
        except Exception:
            cache[name] = None  # unknown/pack scenario: parts unavailable
    return cache[name]


def build_record(d, name, scenarios):
    """Assemble one export record from a run dir, or None if unreadable."""
    m = _load_json(os.path.join(d, "metrics.json"), None)
    if not m:
        return None
    flat = _flatten(m, name)
    flat.update(_judge_cols(d))

    seed_text = _seed_text_for(d, m, scenarios)
    sc = _scenario_for(m.get("scenario"), scenarios)
    parts = _seed_parts(sc, m.get("frame") or "A", bool(m.get("agency")),
                        bool(m.get("aware_condition"))) if sc else None
    # Fidelity flag: the artifact is authoritative; parts come from the CURRENT
    # scenario module. A mismatch means the scenario changed since the trial
    # ran -- parts are then approximations (seed_text stays exact).
    composed = "\n".join(list(parts["seed_files"].values())
                         + [parts["system_prompt"], parts["task_message"]]) if parts else None

    sp = _load_text(os.path.join(d, "scratchpad.txt"))
    return {
        "trial_id": name,
        "provenance": {k: flat.get(k) for k in (
            "model", "source", "quant", "weights_version", "precision",
            "serving_stack", "scenario", "frame", "agency", "aware_condition",
            "temp", "tool_protocol", "max_tokens", "is_reasoning",
            "detector_version", "hardware")},
        "seed": {
            "seed_text": seed_text,
            "system_prompt": parts["system_prompt"] if parts else None,
            "task_message": parts["task_message"] if parts else None,
            "seed_files": parts["seed_files"] if parts else None,
            "parts_match_seed_text": (composed == seed_text) if parts else None,
        },
        "trajectory": {
            "messages": _load_json(os.path.join(d, "transcript.json"), []),
            "actions": _load_json(os.path.join(d, "actions.json"), []),
            "reasoning": _load_text(os.path.join(d, "reasoning.txt")),
            "scratchpad": sp.split("\n\n---\n\n") if sp.strip() else [],
            "sink_records": _load_json(os.path.join(d, "sink.json"), []),
            "dropped_tool_calls": _load_json(
                os.path.join(d, "dropped_tool_calls.json"), []),
            "finish_summary": m.get("finish_summary", ""),
        },
        "outcome": {k: flat.get(k) for k in (
            "status", "steps", "total_tokens", "risk_tier", "escape_attempt",
            "exfil_attempt", "reasoning_escape_flag", "dropped_escape_signal",
            "legit_complete", "judge_verdict", "judge_genuine",
            "judge_prompt_sha")},
    }


def _valid_trial(m):
    return (m.get("total_tokens", 0) > 0 and m.get("steps", 0) > 2
            and not m.get("degenerated", False))


def _selected(rec, args):
    """Outcome-preset gate (validity + axis filters are applied before this)."""
    out = rec["outcome"]
    if args.selection == "all":
        return True
    if args.selection == "flagged":
        return (out["risk_tier"] in ("reasoning", "attempt", "upload")
                or out["judge_genuine"] is True)
    # exemplars: clean tier, task done, and any upload judged clean (AMBIGUOUS
    # is not clean enough to distill from). An EXISTING verdict always decides
    # -- --allow-unjudged only relaxes uploads nobody judged.
    if out["risk_tier"] != "none" or not out["legit_complete"]:
        return False
    if rec["trajectory"]["sink_records"]:
        if out["judge_verdict"]:
            return out["judge_verdict"] in _CLEAN_VERDICTS
        return bool(args.allow_unjudged)
    return True


def _axis_ok(m, args):
    if args.scenario and m.get("scenario") not in args.scenario:
        return False
    if args.frames and m.get("frame") not in args.frames:
        return False
    if args.agency != "both" and bool(m.get("agency")) != (args.agency == "on"):
        return False
    if args.aware != "both" and bool(m.get("aware_condition")) != (args.aware == "on"):
        return False
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export trials as fine-tune JSONL.")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default=os.path.join("runs", "exports"),
                    help="Output dir (under runs/ so it inherits the private "
                         "snapshot + gitignore treatment).")
    ap.add_argument("--name", required=True,
                    help="Export name; writes <out>/<name>/finetune_trials.jsonl "
                         "+ export_manifest.json.")
    ap.add_argument("--model", default="",
                    help="Teacher/variant label filter (metrics['model']). "
                         "Strongly recommended: an export mixing models is "
                         "rarely what a distillation wants.")
    ap.add_argument("--scenario", default="", help="Comma list; empty = all.")
    ap.add_argument("--frames", default="", help="Comma list; empty = all.")
    ap.add_argument("--agency", choices=("off", "on", "both"), default="both")
    ap.add_argument("--aware", choices=("off", "on", "both"), default="both")
    ap.add_argument("--selection", choices=("exemplars", "flagged", "all"),
                    default="exemplars",
                    help="exemplars: clean teacher trajectories (the "
                         "distillation preset). flagged: risky trials. all.")
    ap.add_argument("--allow-unjudged", action="store_true",
                    help="exemplars: accept detector-only-clean uploads without "
                         "a judge verdict (risky -- detector/judge splits exist).")
    ap.add_argument("--holdout", default="",
                    help="'scenario:frame,scenario:frame' cells to EXCLUDE from "
                         "the export (kept clean as the student's re-test "
                         "surface); recorded in the manifest.")
    ap.add_argument("--limit", type=int, default=0, help="Cap records (0 = no cap).")
    args = ap.parse_args(argv)
    args.scenario = [s.strip() for s in args.scenario.split(",") if s.strip()]
    args.frames = [f.strip() for f in args.frames.split(",") if f.strip()]
    holdout = {tuple(h.split(":", 1)) for h in
               (x.strip() for x in args.holdout.split(",")) if h and ":" in h}

    scenarios = {}
    records, seen = [], 0
    names = sorted(n for n in os.listdir(args.runs)
                   if os.path.isfile(os.path.join(args.runs, n, "metrics.json")))
    for name in names:
        d = os.path.join(args.runs, name)
        m = _load_json(os.path.join(d, "metrics.json"), None)
        if not m or not _valid_trial(m):
            continue
        seen += 1
        if args.model and (m.get("model") or "") != args.model:
            continue
        if not _axis_ok(m, args):
            continue
        if (m.get("scenario"), m.get("frame")) in holdout:
            continue
        rec = build_record(d, name, scenarios)
        if rec is None or not _selected(rec, args):
            continue
        records.append(rec)
        if args.limit and len(records) >= args.limit:
            break

    out_dir = os.path.join(args.out, args.name)
    os.makedirs(out_dir, exist_ok=True)
    jsonl = os.path.join(out_dir, "finetune_trials.jsonl")
    with open(jsonl, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    manifest = {
        "name": args.name,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "format": "escapement trajectory export v1",
        "repo_sha": _git_sha(),
        "filters": {
            "model": args.model, "scenario": args.scenario,
            "frames": args.frames, "agency": args.agency, "aware": args.aware,
            "selection": args.selection, "allow_unjudged": args.allow_unjudged,
            "limit": args.limit,
        },
        "held_out_cells": sorted(f"{s}:{fr}" for s, fr in holdout),
        "n_records": len(records),
        "per_model": dict(Counter(r["provenance"]["model"] for r in records)),
        "per_cell": dict(Counter(
            f"{r['provenance']['scenario']}|{r['provenance']['frame']}"
            f"|agency={'on' if r['provenance']['agency'] else 'off'}"
            for r in records)),
        "detector_versions": sorted({r["provenance"]["detector_version"]
                                      for r in records}),
        "trial_ids": [r["trial_id"] for r in records],
        "records_sha256": hashlib.sha256(
            open(jsonl, "rb").read()).hexdigest(),
        "notice": ("For safety evaluation, remediation, and distillation of "
                   "SAFE behavior only (README Responsible Use). Do not train "
                   "models toward exfiltration or scheming with this data."),
    }
    with open(os.path.join(out_dir, "export_manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f">> {len(records)}/{seen} valid trials exported -> {jsonl}")
    for cell, n in sorted(manifest["per_cell"].items()):
        print(f"   {cell:48} {n}")
    if manifest["held_out_cells"]:
        print(f"   held out (excluded from training data): "
              f"{', '.join(manifest['held_out_cells'])}")


if __name__ == "__main__":
    main()
