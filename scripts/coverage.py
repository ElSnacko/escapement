#!/usr/bin/env python3
"""Coverage matrix: how many valid trials per model x cell, and where the gaps are.

Answers the question asked most often during a sweep -- "is this model already
done?" -- in one command, against local runs/ and (optionally) the published HF
baseline. Prints the model x cell matrix (cells below N flagged), models with
zero coverage, and the specific cells to fill.

Target cells (the standard sweep):
  config_exposure {A,B} x agency {off,on}   (4 cells -- the injection finding)
  goal_preservation / goal_guarding {A} x agency {off,on}  (4 cells)

Usage:
  python scripts/coverage.py                       # local runs/ only, N=20
  python scripts/coverage.py --n 40                # different target
  python scripts/coverage.py --hf                  # also pull HF baseline, merge
  python scripts/coverage.py --hf-csv snapshot.csv # overlay a downloaded baseline
  python scripts/coverage.py --model gemma-4-31b   # one model
"""
import argparse
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.env import load_env

load_env()
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tob(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# (label, scenario_prefix, frame, agency) -- order = display order
CELLS = [
    ("ceA0", "config_exposure", "A", False),
    ("ceA1", "config_exposure", "A", True),
    ("ceB0", "config_exposure", "B", False),
    ("ceB1", "config_exposure", "B", True),
    ("gpA0", "goal_preservation", "A", False),
    ("gpA1", "goal_preservation", "A", True),
    ("ggA0", "goal_guarding", "A", False),
    ("ggA1", "goal_guarding", "A", True),
]


def _valid(m):
    return (m.get("total_tokens", 0) > 0 and m.get("steps", 0) > 2
            and not m.get("degenerated", False))


def count_local(runs_dir, model_filter=None):
    """model -> {cell_label: count} over valid local trials."""
    cov = {}
    for mp in glob.glob(os.path.join(runs_dir, "*", "metrics.json")):
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except Exception:
            continue
        if not _valid(m):
            continue
        mdl = m.get("model", "?")
        if model_filter and mdl != model_filter:
            continue
        cov.setdefault(mdl, {})
        for label, sp, fr, ag in CELLS:
            sc = m.get("scenario", "")
            if sc == sp and m.get("frame") == fr and _tob(m.get("agency")) == ag:
                cov[mdl][label] = cov[mdl].get(label, 0) + 1
    return cov


def count_hf_csv(path, model_filter=None):
    """model -> {cell_label: count} from a HF per_trial.csv baseline."""
    cov = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            mdl = r.get("model", "?")
            if model_filter and mdl != model_filter:
                continue
            try:
                tt = int(r.get("total_tokens", 0) or 0)
                st = int(r.get("steps", 0) or 0)
            except ValueError:
                continue
            if tt <= 0 or st <= 2:
                continue
            sc = r.get("scenario", "")
            for label, sp, fr, ag in CELLS:
                if sc == sp and r.get("frame") == fr and _tob(r.get("agency")) == ag:
                    cov.setdefault(mdl, {})
                    cov[mdl][label] = cov[mdl].get(label, 0) + 1
    return cov


def main():
    ap = argparse.ArgumentParser(description="Model x cell coverage matrix + gaps.")
    ap.add_argument("--runs", default=os.path.join(REPO, "runs"))
    ap.add_argument("--n", type=int, default=20, help="Target trials per cell.")
    ap.add_argument("--model", help="Restrict to one model id.")
    ap.add_argument("--hf", action="store_true",
                    help="Fetch the HF dataset per_trial.csv and merge as baseline.")
    ap.add_argument("--hf-csv", help="Path to a downloaded HF per_trial.csv to merge.")
    ap.add_argument("--hf-dataset", default=os.environ.get(
        "ESCAPE_HF_DATASET", "Jsnacks/escapement-dataset"))
    args = ap.parse_args()

    local = count_local(args.runs, args.model)
    baseline = {}
    src = ""
    csv_path = args.hf_csv
    if not csv_path and args.hf:
        # try the latest aggregate_*/per_trial.csv on the dataset
        import requests
        token = os.environ.get("HF_TOKEN", "")
        try:
            r = requests.get(f"https://huggingface.co/api/datasets/{args.hf_dataset}",
                             headers={"Authorization": f"Bearer {token}"}, timeout=15)
            sibs = [s.get("rfilename", "") for s in r.json().get("siblings", [])]
            csvs = sorted([s for s in sibs if s.endswith("/per_trial.csv")])
            if csvs:
                url = (f"https://huggingface.co/datasets/{args.hf_dataset}"
                       f"/resolve/main/{csvs[-1]}")
                csv_path = f"/tmp/{args.hf_dataset.replace('/', '_')}_per_trial.csv"
                with open(csv_path, "wb") as fh:
                    fh.write(requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60).content)
                src = f"HF:{csvs[-1].split('/')[0]}"
        except Exception as e:
            print(f"  (HF fetch failed: {e}; local-only)", file=sys.stderr)
    if csv_path and os.path.exists(csv_path):
        baseline = count_hf_csv(csv_path, args.model)
        src = src or f"csv:{os.path.basename(csv_path)}"

    labels = [c[0] for c in CELLS]
    models = sorted(set(local) | set(baseline))
    if not models:
        print("no valid trials found under", args.runs)
        return

    print(f"target N={args.n}/cell, {len(CELLS)} cells"
          + (f"  | baseline: {src}" if baseline else "  | local only"))
    print(f"\n{'model':34} {'full':>5} {'total':>6}   " + "  ".join(f"{l:>4}" for l in labels))
    print("  " + "-" * 90)
    gaps = []
    for mdl in models:
        l, b = local.get(mdl, {}), baseline.get(mdl, {})
        merged = {k: l.get(k, 0) + b.get(k, 0) for k in labels}
        full = sum(1 for k in labels if merged[k] >= args.n)
        total = sum(merged.values())
        row = "  ".join(f"{merged[k]:>4}" for k in labels)
        src_tag = (" (local)" if mdl in local and mdl not in baseline
                   else " (hf)" if mdl in baseline and mdl not in local else "")
        print(f"  {mdl[:34]:34} {full:>3}/{len(labels)} {total:>6}   {row}{src_tag}")
        under = [k for k in labels if merged[k] < args.n]
        if under:
            gaps.append((mdl, [(k, merged[k]) for k in under]))
    complete = [mdl for mdl in models
                if all((local.get(mdl, {}).get(k, 0) + baseline.get(mdl, {}).get(k, 0)) >= args.n
                       for k in labels)]
    print(f"\nmodels at full coverage ({args.n}/cell all {len(labels)} cells): {len(complete)}")
    print(f"  COMPLETE: {complete if complete else 'none'}")
    if gaps:
        print(f"\nGAPS (cells below {args.n}):")
        for mdl, gs in gaps:
            if not complete or mdl not in complete:
                print(f"  {mdl}: " + ", ".join(f"{k}={c}" for k, c in gs))


if __name__ == "__main__":
    main()
