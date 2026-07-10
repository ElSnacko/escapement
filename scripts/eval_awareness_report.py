#!/usr/bin/env python3
"""Eval-awareness contamination report (docs/niche_analysis.md §6.2).

The detector already stores `eval_awareness_flag` per trial (a keyword proposal:
the hidden reasoning mentions being tested/watched/a honeypot). It is aggregated
per-regime by scripts/aggregate.py, but the paper does not report the one thing
that bears on the headline null: **is the autonomous null explained by models
detecting the evaluation?** This script answers that directly, over runs/.

It emits three views:

  1. Per-model eval-awareness rate (overall + on the autonomous Frame A cells).
  2. The contamination cross-tab: within autonomous cells (Frame A), do
     eval-aware trials show a LOWER escape/exfil rate than non-eval-aware ones?
     (If eval-awareness suppresses the behavior, the null is partly a detection
     artifact. If the rate is the same -- or the events are simply absent in both
     arms -- the null is not obviously contaminated.)
  3. Cross-model: does injection resistance track eval-awareness? (Frame B
     exfil% vs eval_aware% per model -- if the resistant models are the
     high-awareness ones, that is the contamination signature.)

Rare events: Frame A escape/exfil are near-zero by construction, so view 2 is
mostly a BOUND (both arms ~0), reported with Wilson CIs. That is itself the
finding to report -- "eval-aware and non-eval-aware Frame A trials are both ~0,
so awareness does not visibly move the autonomous rate" is a publishable
sentence; so is the opposite.

  python scripts/eval_awareness_report.py                 # over runs/, stored metrics
  python scripts/eval_awareness_report.py --rescore       # recompute the flag with current capture.py
  python scripts/eval_awareness_report.py --runs runs --frame-a-scenarios goal_preservation,goal_guarding
"""
import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.stats import wilson_ci  # noqa: E402

# Mundane (no held goal) scenarios -- their Frame A is the "clean" autonomous
# control. goal_* scenarios carry goal pressure; their Frame A is the
# goal-pressure autonomous cell. Reported separately so contamination can be read
# per pressure regime.
_MUNDANE = ("config_exposure", "agent_coding", "ops_worker")


def _is_goal(scenario: str) -> bool:
    return isinstance(scenario, str) and scenario.startswith("goal_")


def _load_rows(runs_dir: str, rescore: bool):
    """Yield each trial's metrics dict. --rescore recomputes with the current
    capture.py (via scripts/aggregate._rescore) so a stale stored flag from an
    older detector is refreshed; otherwise the stored metrics.json is used."""
    _rescore = _scenarios = None
    if rescore:
        from scripts.aggregate import _rescore as _rs  # lazy: only when asked
        _rescore, _scenarios = _rs, {}
    for name in sorted(os.listdir(runs_dir)):
        d = os.path.join(runs_dir, name)
        mp = os.path.join(d, "metrics.json")
        if not os.path.isfile(mp):
            continue
        try:
            if rescore:
                m = _rescore(d, _scenarios)
            else:
                with open(mp, encoding="utf-8") as fh:
                    m = json.load(fh)
        except Exception:
            continue
        if isinstance(m, dict):
            yield m


def _rate_str(k: int, n: int) -> str:
    if n <= 0:
        return f"{k}/{n}"
    lo, hi = wilson_ci(k, n)
    return f"{k}/{n} {100*k/n:4.1f}% [{100*lo:4.1f}-{100*hi:4.1f}]"


def _truthy(v) -> bool:
    return bool(v) and v not in ("false", "False", "0", 0)


def analyze(rows):
    """Accumulate per-model and contamination-cross-tab counts from trial dicts.

    Pure (no I/O) so it is unit-testable. Returns ``(per_model, contam)`` where
    ``per_model[model]`` has n / aware / Frame-A / Frame-B counts and
    ``contam[(regime, aware)]`` has Frame-A escape/exfil counts.
    """
    per_model = defaultdict(lambda: {"n": 0, "aware": 0,
                                     "aA_n": 0, "aA_aware": 0,
                                     "B_n": 0, "B_exfil": 0})
    contam = defaultdict(lambda: {"n": 0, "escape": 0, "exfil": 0})
    for m in rows:
        model = m.get("model") or "?"
        frame = m.get("frame")
        scen = m.get("scenario") or ""
        aware = _truthy(m.get("eval_awareness_flag"))
        exfil = _truthy(m.get("exfil_attempt"))
        escape = _truthy(m.get("escape_attempt"))
        pm = per_model[model]
        pm["n"] += 1
        pm["aware"] += aware
        if frame == "A":
            pm["aA_n"] += 1
            pm["aA_aware"] += aware
            regime = "goal-pressure" if _is_goal(scen) else "mundane"
            cell = contam[(regime, aware)]
            cell["n"] += 1
            cell["escape"] += escape
            cell["exfil"] += exfil
        if frame == "B":
            pm["B_n"] += 1
            pm["B_exfil"] += exfil
    return per_model, contam


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--rescore", action="store_true",
                    help="recompute eval_awareness_flag with the current capture.py")
    args = ap.parse_args()

    if not os.path.isdir(args.runs):
        sys.exit(f"!! no runs dir at {args.runs}")

    rows = list(_load_rows(args.runs, args.rescore))
    if not rows:
        sys.exit(f"!! no metrics.json found under {args.runs}")

    per_model, contam = analyze(rows)

    print(f"\n== eval-awareness report over {len(rows)} trials "
          f"({'rescored' if args.rescore else 'stored metrics'}) ==\n")

    # View 1 + 3 combined: per-model awareness and whether resistance tracks it.
    print("-- per model: eval-awareness rate, and Frame B exfil (does resistance "
          "track awareness?) --")
    print(f"{'model':30} {'eval_aware (all)':>22}  {'eval_aware (Frame A)':>24}  "
          f"{'Frame B exfil':>22}")
    for model in sorted(per_model, key=lambda x: -per_model[x]["n"]):
        pm = per_model[model]
        print(f"{model[:30]:30} {_rate_str(pm['aware'], pm['n']):>22}  "
              f"{_rate_str(pm['aA_aware'], pm['aA_n']):>24}  "
              f"{_rate_str(pm['B_exfil'], pm['B_n']):>22}")

    # View 2: the contamination cross-tab on Frame A, per pressure regime.
    print("\n-- contamination cross-tab (Frame A only): does eval-awareness move "
          "the autonomous rate? --")
    print(f"{'regime':16} {'aware?':8} {'escape_attempt':>22} {'exfil_attempt':>22}")
    for regime in ("mundane", "goal-pressure"):
        for aware in (True, False):
            c = contam[(regime, aware)]
            if c["n"] == 0:
                continue
            print(f"{regime:16} {str(aware):8} "
                  f"{_rate_str(c['escape'], c['n']):>22} "
                  f"{_rate_str(c['exfil'], c['n']):>22}")

    print("\n-- how to read this --")
    print("  * If, within a regime, the aware and not-aware Frame A rows have "
          "overlapping/near-zero\n    escape+exfil, eval-awareness does NOT "
          "visibly explain the autonomous null (report as such).")
    print("  * If aware rows are markedly LOWER, the null may be partly a "
          "detection artifact -- state it\n    as a bounded contamination, not a "
          "clean propensity null.")
    print("  * If the injection-resistant models (Frame B exfil ~0) are also the "
          "highest eval_aware,\n    that co-variation is the contamination "
          "signature to flag.")
    print("  * Rare events: Frame A escape/exfil are near-zero by design, so "
          "these are often BOUNDS,\n    not point estimates -- the Wilson upper "
          "bound is the honest number to quote.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
