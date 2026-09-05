#!/usr/bin/env python3
"""Compare two model labels cell-by-cell (the pre/post fine-tune report).

  python scripts/compare.py --a gemma-4-31b --b gemma-4-31b+distill-v1 \
      [--scenario config_exposure] [--frames B] [--export-manifest runs/exports/t/export_manifest.json]

Per cell (scenario x frame x agency x aware): k/n + Wilson CI per outcome for
BOTH sides, Fisher exact on the 2x2, and delta (B - A). Headline outcome is
judge-confirmed GENUINE (judged trials only); detector tiers follow. CMH across
cells gives the stratified common-effect test (core/stats.py -- statsmodels-
cross-checked; degenerate all-zero cells contribute nothing, by design).

Contamination: pass --export-manifest (repeatable) pointing at the
export_finetune.py manifest(s) the fine-tune trained on. Each cell is then
labelled with train/test overlap and the CMH is run BOTH over all cells and
over held-out cells only -- after distilling from teacher trajectories, the
held-out verdict is the one that generalizes; trained-on cells only show
whether the eval was memorized.

Honesty rails:
  * cells where both sides have k=0, or either n < --min-n, print an
    UNDERPOWERED marker instead of reading as "no change";
  * detector_version heterogeneity across the compared trials warns (rescore
    one side or both before comparing).
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.stats import cochran_mantel_haenszel, fisher_exact_2x2, wilson_ci  # noqa: E402
from aggregate import _flatten, _judge_cols  # noqa: E402

# outcome -> (label, denominator) -- mirrors aggregate's OUTCOMES semantics.
OUTCOMES = (
    ("genuine", "judge-confirmed self-bootstrap (judged only)"),
    ("exfil", "upload tier (exfil_attempt)"),
    ("escape", "attempt+ (escape_attempt)"),
    ("rflag", "reasoning flag"),
)


def load_sides(runs_dir, labels, args):
    """-> {(cell): (rows_a, rows_b)} for the two labels, real trials only."""
    import json
    by_cell = defaultdict(lambda: ([], []))
    versions = set()
    for name in sorted(os.listdir(runs_dir)):
        d = os.path.join(runs_dir, name)
        mp = os.path.join(d, "metrics.json")
        if not os.path.isfile(mp):
            continue
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except Exception:
            continue
        model = m.get("model") or ""
        if model not in labels:
            continue
        if not (m.get("total_tokens", 0) > 0 and m.get("steps", 0) > 2
                and not m.get("degenerated", False)):
            continue
        if args.scenario and m.get("scenario") not in args.scenario:
            continue
        if args.frames and m.get("frame") not in args.frames:
            continue
        if args.agency != "both" and bool(m.get("agency")) != (args.agency == "on"):
            continue
        if args.aware != "both" and bool(m.get("aware_condition")) != (args.aware == "on"):
            continue
        row = _flatten(m, name)
        row.update(_judge_cols(d))
        cell = (m.get("scenario"), m.get("frame"),
                bool(m.get("agency")), bool(m.get("aware_condition")))
        by_cell[cell][1 if model == args.b else 0].append(row)
        if row.get("detector_version"):
            versions.add(row["detector_version"])
    return by_cell, versions


def _cell_counts(rows, outcome):
    """(k, n) for one outcome over one side's rows."""
    if outcome == "genuine":
        judged = [r for r in rows if r.get("judge_verdict") != ""]
        return (sum(1 for r in judged if r.get("judge_genuine") is True), len(judged))
    key = {"exfil": "exfil_attempt", "escape": "escape_attempt",
           "rflag": "reasoning_escape_flag"}[outcome]
    return (sum(1 for r in rows if r.get(key)), len(rows))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pre/post or A/B model comparison.")
    ap.add_argument("--a", required=True, help="Baseline model label (metrics['model']).")
    ap.add_argument("--b", required=True, help="Comparison label (e.g. base+distill-v1).")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--scenario", default="", help="Comma list; empty = all.")
    ap.add_argument("--frames", default="", help="Comma list; empty = all.")
    ap.add_argument("--agency", choices=("off", "on", "both"), default="both")
    ap.add_argument("--aware", choices=("off", "on", "both"), default="both")
    ap.add_argument("--min-n", type=int, default=20,
                    help="Below this per-side n (or both k=0) a cell prints "
                         "UNDERPOWERED instead of reading as 'no change'.")
    ap.add_argument("--export-manifest", action="append", default=[],
                    metavar="PATH",
                    help="export_finetune.py manifest trained on (repeatable); "
                         "enables the train/test overlap split.")
    ap.add_argument("--out", default="", help="CSV path (default runs/compare_<a>_vs_<b>.csv).")
    args = ap.parse_args(argv)
    args.scenario = [s.strip() for s in args.scenario.split(",") if s.strip()]
    args.frames = [f.strip() for f in args.frames.split(",") if f.strip()]

    train_ids = set()
    for p in args.export_manifest:
        import json
        man = json.load(open(p, encoding="utf-8"))
        train_ids.update(man.get("trial_ids") or [])

    labels = [args.a, args.b]
    by_cell, versions = load_sides(args.runs, set(labels), args)
    if not by_cell:
        sys.exit(f"no valid trials for {args.a!r} / {args.b!r} under the filters")
    if len(versions) > 1:
        print(f"!! WARNING: corpus mixes detector versions "
              f"({', '.join(sorted(versions))}) -- rescore for uniform scoring "
              f"before trusting deltas.", file=sys.stderr)

    rows_out = []
    print(f"\n{args.a}  vs  {args.b}"
          + (f"  | train set: {len(train_ids)} trials" if train_ids else ""))
    for outcome, desc in OUTCOMES:
        print(f"\n== {outcome}: {desc} ==")
        print(f"  {'cell':40} {'A k/n (Wilson CI)':>24} {'B k/n (Wilson CI)':>24} "
              f"{'delta':>7} {'p(fisher)':>9}")
        strata_all, strata_heldout = [], []
        for cell in sorted(by_cell, key=lambda c: (str(c[0]), str(c[1]))):
            ra, rb = by_cell[cell]
            ka, na = _cell_counts(ra, outcome)
            kb, nb = _cell_counts(rb, outcome)
            label = f"{cell[0]}|{cell[1]}|ag={'on' if cell[2] else 'off'}" \
                    f"|aw={'on' if cell[3] else 'off'}"
            train_hit = sum(1 for r in ra + rb if r["trial_id"] in train_ids)
            underpowered = ((ka == 0 and kb == 0)
                            or na < args.min_n or nb < args.min_n)
            la, ha = wilson_ci(ka, na) if na else (0.0, 0.0)
            lb, hb = wilson_ci(kb, nb) if nb else (0.0, 0.0)
            if na and nb:
                p = fisher_exact_2x2(ka, na - ka, kb, nb - kb)
                print(f"  {label:40} {ka}/{na} ({la:.3f}-{ha:.3f})"
                      + f"  {kb}/{nb} ({lb:.3f}-{hb:.3f})"
                      + f" {kb / nb - ka / na:+7.3f} {p:9.4f}")
            else:
                print(f"  {label:40} insufficient data (nA={na}, nB={nb})")
            if underpowered:
                print(f"  {'':40} UNDERPOWERED"
                      + (" (both k=0 -- no evidence of no-change)"
                         if ka == 0 and kb == 0 else ""))
            if train_ids and train_hit:
                print(f"  {'':40} [train overlap: {train_hit} of "
                      f"{na + nb} trials in the export manifest]")
            # stratum for CMH: rows = A, B; cols = event, no-event.
            if na and nb and (ka + kb) > 0 and ((na - ka) + (nb - kb)) > 0:
                strata_all.append((ka, na - ka, kb, nb - kb))
                if not train_hit:
                    strata_heldout.append((ka, na - ka, kb, nb - kb))
            rows_out.append({
                "outcome": outcome, "cell": label,
                "a_k": ka, "a_n": na,
                "a_ci": f"{la:.3f}-{ha:.3f}" if na else "",
                "b_k": kb, "b_n": nb,
                "b_ci": f"{lb:.3f}-{hb:.3f}" if nb else "",
                "delta": round(kb / nb - ka / na, 4) if (na and nb) else "",
                "fisher_p": round(p, 5) if (na and nb) else "",
                "underpowered": underpowered,
                "train_overlap_trials": train_hit,
            })
        cmh_sets = [("all cells", strata_all)]
        if train_ids:
            cmh_sets.append(("held-out cells only", strata_heldout))
        for name, strata in cmh_sets:
            if not strata:
                continue
            cmh = cochran_mantel_haenszel(strata)
            sig = "" if cmh["ci_low"] <= 1 <= cmh["ci_high"] else "  (CI excludes 1)"
            print(f"  CMH {name} ({cmh['n_strata_used']} strata): "
                  f"chi2={cmh['chi2']:.2f} p={cmh['p']:.4f} "
                  f"OR={cmh['or_mh']:.3f} "
                  f"[{cmh['ci_low']:.3f},{cmh['ci_high']:.3f}]{sig}")

    out = args.out or os.path.join(
        args.runs, f"compare_{args.a}_vs_{args.b}.csv".replace("/", "_"))
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0]))
        w.writeheader()
        w.writerows(rows_out)
    print(f"\n>> {len(rows_out)} cell-outcome rows -> {out}")


if __name__ == "__main__":
    main()
