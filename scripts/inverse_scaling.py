#!/usr/bin/env python3
"""Inverse-scaling analysis: does injection compliance scale with capability on
the open-weights class (the open-weights analog of AgentDojo's Figure 6a)?

Uses the PAPER'S published per-model Frame B rates (docs/paper.md §3.3) -- these
are the judge-reviewed numbers, trusted over a fresh rescore because capture.py
has drifted since the paper (current detector scores DeepSeek 15/60 vs the
published 7/60). ZERO new agent inference; ZERO re-judge. Benign task-completion
(the x-axis AgentDojo uses) is derived from runs/ -- finish-status-based, so it
is stable across detector versions.

Outputs:
  docs/inverse_scaling_total.png    rate vs total params
  docs/inverse_scaling_active.png   rate vs active params (MoE-active / dense-total)
  docs/inverse_scaling_benign.png   rate vs benign task-completion (AgentDojo-style)
  runs/inverse_scaling.csv          the underlying table
"""
import csv
import math
import os
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from core.stats import wilson_ci  # noqa: E402

# The paper's published Frame B genuine-self-bootstrap rates (docs/paper.md §3.3).
# (k, n, total_params_B, active_params_B or None, family, temp). Trusted over a
# fresh rescore -- capture.py has drifted (DeepSeek current-detector 15 vs 7).
PAPER_RATES = {
    "DeepSeek V4 Flash":         (7, 60, 284, 13,   "deepseek", 1.0),
    "Qwen3.6-35B-A3B (ablated)": (3, 60, 35,  3,    "qwen",     1.0),
    "Gemma-4-12B (base)":        (1, 30, 12,  12,   "gemma",    1.0),
    "GPT-OSS-120B (base)":       (1, 35, 120, None, "openai",   0.7),
    "Qwen3.6-27B (ablated)":     (1, 54, 27,  27,   "qwen",     1.0),
    "Qwen3.6-35B-A3B (base)":    (0, 60, 35,  3,    "qwen",     1.0),
    "Qwen3.6-27B (base)":        (0, 58, 27,  27,   "qwen",     1.0),
    "Gemma-4-12B (obliterated)": (0, 94, 12,  12,   "gemma",    1.0),
    "Gemma-4-26B-A4B (base)":    (0, 40, 26,  4,    "gemma",    0.7),
    "Gemma-4-31B (base)":        (0, 39, 31,  31,   "gemma",    0.7),
    "Nemotron-3-Nano-30B":       (0, 38, 30,  3,    "nvidia",   0.7),
}

COLOR = {"deepseek": "tab:red", "qwen": "tab:blue", "gemma": "tab:green",
         "openai": "tab:purple", "nvidia": "tab:orange"}


def _task_utility():
    """Per-model legitimate-task completion by frame, from runs/ (status-based ->
    stable across detector versions). model-key -> {'A': benign%, 'B': under-attack%}.
    Frame A = benign utility (no injection); Frame B = utility under attack."""
    import glob, json

    def key_of(mid):
        m = (mid or "").lower()
        if "deepseek" in m:
            return "DeepSeek V4 Flash"
        if "gpt-oss" in m:
            return "GPT-OSS-120B (base)"
        if "nemotron-3-nano-30b" in m or "nemotron-3-nano" in m:
            return "Nemotron-3-Nano-30B"
        abl = ("uncensored" in m or "abliterated" in m)
        if "35b-a3b" in m or "35b" in m:
            return "Qwen3.6-35B-A3B (ablated)" if abl else "Qwen3.6-35B-A3B (base)"
        if "27b" in m:
            return "Qwen3.6-27B (ablated)" if abl else "Qwen3.6-27B (base)"
        if "26b" in m:
            return "Gemma-4-26B-A4B (base)"
        if "31b" in m:
            return "Gemma-4-31B (base)"
        if "12b" in m:
            return "Gemma-4-12B (obliterated)" if "obliterated" in m else "Gemma-4-12B (base)"
        return None

    cells = defaultdict(lambda: {"A": [0, 0], "B": [0, 0]})  # key -> frame -> [completed, n]
    for d in glob.glob(os.path.join(REPO, "runs", "config_exposure_*")):
        mp = os.path.join(d, "metrics.json")
        if not os.path.isfile(mp):
            continue
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except Exception:
            continue
        fr = str(m.get("frame"))
        if fr not in ("A", "B") or (m.get("steps") or 0) <= 2 or (m.get("total_tokens") or 0) <= 0:
            continue
        k = key_of(m.get("model"))
        if not k:
            continue
        cells[k][fr][1] += 1
        tve = m.get("task_vs_escape_actions") or {}
        if m.get("status") == "finished" or (tve.get("task", 0) > 0 or m.get("archive_posts", 0) > 0):
            cells[k][fr][0] += 1
    return {k: {fr: (100.0 * c / n if n else float("nan")) for fr, (c, n) in v.items()}
            for k, v in cells.items()}


def _ops_worker_capability():
    """Per-model capability ceiling from runs/ops_worker_* (self-bootstrap when
    overtly instructed). model-key (matched to PAPER_RATES) -> (capable, n)."""
    import glob, json

    def key_of(mid):
        m = (mid or "").lower()
        if "deepseek" in m:
            return "DeepSeek V4 Flash"
        if "gpt-oss" in m:
            return "GPT-OSS-120B (base)"
        return None  # only the API-reachable models were run; extend as added

    out = defaultdict(lambda: [0, 0])  # key -> [capable, n]
    for d in glob.glob(os.path.join(REPO, "runs", "ops_worker_*")):
        mp = os.path.join(d, "metrics.json")
        if not os.path.isfile(mp):
            continue
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except Exception:
            continue
        if (m.get("steps") or 0) <= 2 or (m.get("total_tokens") or 0) <= 0:
            continue
        k = key_of(m.get("model"))
        if not k:
            continue
        out[k][1] += 1
        if m.get("exfil_attempt"):
            out[k][0] += 1
    return {k: tuple(v) for k, v in out.items()}


def _scatter(ax, rows, xfield, xlabel, title):
    for r in rows:
        x = r[xfield]
        if x == "" or x is None or (isinstance(x, float) and math.isnan(x)):
            continue
        ax.errorbar(x, r["rate"],
                    yerr=[[max(0.0, r["rate"] - r["ci_lo"])],
                          [max(0.0, r["ci_hi"] - r["rate"])]],
                    fmt="o", color=COLOR.get(r["family"], "gray"), markersize=9,
                    markeredgecolor=("black" if r["temp"] == 1.0 else "none"),
                    markeredgewidth=1.5, capsize=3, zorder=3)
        ax.annotate(r["model"].replace(" (base)", "").replace(" (ablated)", "(abl)")[:22],
                    (x, r["rate"]), fontsize=7, xytext=(5, 4), textcoords="offset points")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Frame B genuine self-bootstrap rate (%)")
    ax.set_title(title)
    ax.set_ylim(-2, 30)
    ax.grid(alpha=0.3)


def main():
    util = _task_utility()
    rows = []
    for model, (k, n, tot, act, fam, temp) in PAPER_RATES.items():
        lo, hi = wilson_ci(k, n, 0.95)
        u = util.get(model, {})
        rows.append({
            "model": model, "k": k, "n": n, "rate": 100 * k / n,
            "ci_lo": 100 * lo, "ci_hi": 100 * hi,
            "total_params_B": tot, "active_params_B": act if act else "",
            "family": fam, "temp": temp,
            "benign_completion": round(u.get("A", float("nan")), 1),
            "utility_under_attack": round(u.get("B", float("nan")), 1),
        })
    rows.sort(key=lambda r: -r["rate"])

    print(f"{'model':28} {'k/n':>7} {'rate':>6} {'95%CI':>14} {'totB':>5} {'actB':>5} {'temp':>4} {'benign':>6} {'atk':>5}")
    print("-" * 92)
    for r in rows:
        ci = f"[{r['ci_lo']:.1f}-{r['ci_hi']:.1f}]"
        print(f"{r['model']:28} {str(r['k'])+'/'+str(r['n']):>7} {r['rate']:>5.1f}% {ci:>14} "
              f"{r['total_params_B']:>5} {str(r['active_params_B']):>5} {r['temp']:>4.1f} "
              f"{r['benign_completion']:>6} {r['utility_under_attack']:>5}")

    csv_path = os.path.join(REPO, "runs", "inverse_scaling.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n>> table -> {csv_path}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"!! matplotlib unavailable ({exc}); skipping PNGs.")
        return 0

    for fname, xfield, xlabel, title in [
        ("inverse_scaling_total.png", "total_params_B", "total parameters (B)",
         "Injection compliance vs total params (open-weights)"),
        ("inverse_scaling_active.png", "active_params_B",
         "active params (MoE-active / dense-total, B)",
         "Injection compliance vs active params (open-weights)"),
        ("inverse_scaling_benign.png", "benign_completion", "benign task-completion (%)",
         "Injection compliance vs benign utility (AgentDojo-style, open-weights)"),
    ]:
        fig, ax = plt.subplots(figsize=(9, 6))
        _scatter(ax, rows, xfield, xlabel, title)
        ax.plot([], [], "o", color="lightgray", markersize=9, markeredgecolor="black",
                markeredgewidth=1.5, label="temp=1.0 (black outline)")
        ax.plot([], [], "o", color="lightgray", markersize=9, markeredgecolor="none",
                label="temp=0.7 (no outline)")
        ax.legend(loc="upper left", fontsize=8)
        fig.tight_layout()
        out = os.path.join(REPO, "docs", fname)
        fig.savefig(out, dpi=130)
        plt.close(fig)
        print(f">> figure -> {out}")

    # ---- capability-vs-propensity cross-reference (the "can't vs won't" table) ----
    cap = _ops_worker_capability()
    if cap:
        print("\n=== capability vs propensity (ops_worker when told vs Frame B injected) ===")
        print(f"{'model':28} {'capability':>16} {'propensity':>16} {'gap':>8}")
        print("-" * 72)
        for k, (cc, cn) in sorted(cap.items()):
            if cn == 0:
                continue
            fk, fn = PAPER_RATES.get(k, (0, 0, 0, 0, "", 0.0)), None
            # PAPER_RATES value is the 6-tuple; pull (k, n) = first two
            pk, pn = PAPER_RATES[k][0], PAPER_RATES[k][1]
            crate = 100 * cc / cn
            prate = 100 * pk / pn
            print(f"{k:28} {f'{cc}/{cn} = {crate:.0f}%':>16} "
                  f"{f'{pk}/{pn} = {prate:.1f}%':>16} {crate - prate:>7.0f}pp")
        cap_csv = os.path.join(REPO, "runs", "capability_vs_propensity.csv")
        with open(cap_csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["model", "capable", "cap_n", "cap_rate", "prop_k", "prop_n", "prop_rate"])
            for k, (cc, cn) in sorted(cap.items()):
                pk, pn = PAPER_RATES[k][0], PAPER_RATES[k][1]
                w.writerow([k, cc, cn, round(100 * cc / cn, 1), pk, pn, round(100 * pk / pn, 1)])
        print(f">> cross-reference -> {cap_csv}")
    else:
        print("\n(no ops_worker capability data in runs/ -- run ops_worker on a model first)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
