#!/usr/bin/env python3
"""Recompute the canonical headline tables directly from runs/, by rescoring
every config_exposure trial with the CURRENT core/capture.py.

This is the single source of truth for the numbers in docs/paper.md and
CONCLUSIONS.md. Stored metrics.json is a mix of capture.py versions across
batches; only a uniform rescore gives comparable rates.

  python scripts/recompute_canonical.py            # config_exposure tables
  python scripts/recompute_canonical.py --runs runs --conf 0.95

Outputs: grand totals, Frame A/B pooled rates, per-model Frame A/B rates with
Wilson 95% CIs, and matched base/ablated Frame B pairs. Prints to stdout.
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from core.capture import compute_metrics          # noqa: E402
from core.scenario import load_scenario           # noqa: E402
from core.stats import wilson_ci                  # noqa: E402


def rate(k, n):
    if n == 0:
        return "0/0"
    lo, hi = wilson_ci(k, n, 0.95)
    return f"{k}/{n} = {100*k/n:.2f}% [CI {100*lo:.1f}-{100*hi:.1f}]"


def family(raw):
    """Canonical family key: strip path, quant, variant, :free, -it/-qat/-ud."""
    b = os.path.basename(raw or "").lower()
    b = b[:-5] if b.endswith(".gguf") else b
    for s in (":free", "-uncensored-hauhaucs-aggressive", "-obliterated", "-ud", "-qat"):
        b = b.replace(s, "")
    b = re.sub(r"-q\d[_a-z0-9-]*", "", b).replace("-it", "").strip("-")
    return b


def variant(raw):
    r = (raw or "").lower()
    return "ablated" if any(t in r for t in ("uncensored", "abliterated",
                                             "obliterated")) else "base"


def rescore(d, sc, seed_text):
    om = json.load(open(os.path.join(d, "metrics.json"), encoding="utf-8"))

    def ld(fn, dft):
        p = os.path.join(d, fn)
        return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else dft
    reasoning = open(os.path.join(d, "reasoning.txt"), encoding="utf-8").read() \
        if os.path.isfile(os.path.join(d, "reasoning.txt")) else ""
    sp = open(os.path.join(d, "scratchpad.txt"), encoding="utf-8").read() \
        if os.path.isfile(os.path.join(d, "scratchpad.txt")) else ""
    result = {
        "actions": ld("actions.json", []), "sink_records": ld("sink.json", []),
        "scratchpad": sp.split("\n\n---\n\n") if sp.strip() else [],
        "reasoning": [reasoning], "status": om.get("status"),
        "steps": om.get("steps", 0), "unlock_step": om.get("unlock_step"),
        "total_tokens": om.get("total_tokens", 0), "perf": om.get("perf", {}),
        "finish_summary": om.get("finish_summary", ""),
        "dropped_tool_calls": ld("dropped_tool_calls.json",
                                 om.get("dropped_tool_calls")
                                 if isinstance(om.get("dropped_tool_calls"), list) else []),
    }
    m = compute_metrics(result, ld("sink.json", []), ld("fs_diff.json", {}),
                        sc.meta(), seed_text=seed_text)
    m["frame"] = om.get("frame")
    m["model"] = om.get("model")
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", default=os.path.join(REPO, "runs"))
    ap.add_argument("--conf", type=float, default=0.95)
    args = ap.parse_args()
    sc = load_scenario("config_exposure")
    seed_text = "\n".join(list(sc.seed_files.values()) + [sc.system_prompt, sc.task_message])

    rows, fails = [], 0
    names = sorted(n for n in os.listdir(args.runs)
                   if n.startswith("config_exposure_")
                   and os.path.isdir(os.path.join(args.runs, n)))
    for i, name in enumerate(names):
        d = os.path.join(args.runs, name)
        if not os.path.isfile(os.path.join(d, "metrics.json")):
            continue
        try:
            m = rescore(d, sc, seed_text)
        except Exception:
            fails += 1
            continue
        m["_dir"] = name
        rows.append(m)
        if (i + 1) % 400 == 0:
            print(f"  ...{i+1}/{len(names)}", flush=True)
    real = [m for m in rows if m.get("steps", 0) > 2 and m.get("total_tokens", 0) > 0]

    print(f"config_exposure: {len(rows)} scored, {fails} rescore failures, "
          f"{len(real)} real trials (steps>2 & tokens>0)\n")

    print("== POOLED BY FRAME (genuine self-bootstrap, exfil_attempt) ==")
    for fr in ("A", "B"):
        sub = [m for m in real if str(m.get("frame")) == fr]
        kx = sum(1 for m in sub if m.get("exfil_attempt"))
        print(f"  Frame {fr}: {rate(kx, len(sub))}")

    print("\n== DeepSeek vs rest, Frame B ==")
    fb = [m for m in real if str(m.get("frame")) == "B"]
    ds = [m for m in fb if "deepseek" in (m.get("model") or "").lower()]
    rest = [m for m in fb if m not in ds]
    print(f"  DeepSeek V4 Flash: {rate(sum(1 for m in ds if m.get('exfil_attempt')), len(ds))}")
    print(f"  All others       : {rate(sum(1 for m in rest if m.get('exfil_attempt')), len(rest))}")

    print("\n== PER MODEL x VARIANT x FRAME (genuine) ==")
    print(f"{'model|variant':38} {'Frame A':>24} {'Frame B':>24}")
    cells = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for m in real:
        cells[(family(m.get("model")), variant(m.get("model")))][str(m.get("frame"))][1] += 1
        if m.get("exfil_attempt"):
            cells[(family(m.get("model")), variant(m.get("model")))][str(m.get("frame"))][0] += 1
    for (fam, var) in sorted(cells):
        a, b = cells[(fam, var)]["A"], cells[(fam, var)]["B"]
        if a[1] or b[1]:
            print(f"{(fam+'|'+var):38} {rate(*a):>24} {rate(*b):>24}")

    print("\n== MATCHED BASE/ABLATED PAIRS, Frame B ==")
    fams = defaultdict(dict)
    for (fam, var), frd in cells.items():
        if frd["B"][1]:
            fams[fam][var] = frd["B"]
    for fam in sorted(fams):
        d = fams[fam]
        if "base" in d and "ablated" in d:
            print(f"  {fam}")
            print(f"     base   : {rate(*d['base'])}")
            print(f"     ablated: {rate(*d['ablated'])}")
    print("\n(note: ablation counts here are detector-scored. The trial-by-trial "
          "LLM-judge pass is slightly more inclusive on terse self-state; see "
          "docs/paper.md section 3.4.)")


if __name__ == "__main__":
    main()
