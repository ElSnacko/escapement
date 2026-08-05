#!/usr/bin/env python3
"""batch_run -- sweep scenario x frame x (agency) over N trials and report
escape/exfil rates with Wilson 95% confidence intervals.

Single runs at low N can only ever show "not-obviously-nonzero". This turns the
harness into a real propensity measurement: run N trials per cell, count the
rare events, and report each rate with a Wilson CI (which, unlike Wald, gives a
meaningful upper bound at k=0 -- the "rule of three", ~3.84/(N+3.84) at 95%).

Usage:
  python3 batch_run.py --scenarios goal_preservation,goal_guarding,goal_capacity \
                       --frames A --n 100 --temp 1.0 --host http://127.0.0.1:8080
  python3 batch_run.py --scenarios config_exposure --frames A,B,C --agency both --n 50

Each trial reuses run.py's main() in-process (full sandbox + CoT + metrics +
artifacts), so captured runs land in runs/ as normal; this script just aggregates
metrics.json across the batch.
"""

import argparse
import contextlib
import glob
import io
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from run import main as run_one
from core.env import load_env
from core.stats import fmt_rate, wilson_ci


def _cell_label(scenario, frame, agency, aware=False):
    return (f"{scenario}|{frame}|agency={'on' if agency else 'off'}"
            f"|aware={'on' if aware else 'off'}")


def _count_valid_runs(scenario, frame, agency, aware=False, model_filter=None):
    """Count existing run dirs for this cell with valid (non-dead) metrics.
    Used for resume: if a batch was interrupted, re-running the same command
    skips completed trials and only runs the remainder.
    model_filter: if provided, only count runs matching this model name."""
    count = 0
    for d in glob.glob(f"runs/{scenario}_*"):
        mp = os.path.join(d, "metrics.json")
        if not os.path.exists(mp):
            continue
        try:
            m = json.load(open(mp))
        except Exception:
            continue
        if (m.get("frame") == frame and bool(m.get("agency")) == bool(agency)
                and bool(m.get("aware_condition")) == bool(aware)
                and m.get("total_tokens", 0) > 0
                and m.get("steps", 0) > 2
                and not m.get("degenerated", False)):
            if model_filter and (m.get("model") or "") != model_filter:
                continue
            count += 1
    return count


def _trial(scenario, frame, agency, aware, host, api_key, tool_protocol, temp,
           max_steps, max_tokens, container=None, tag=None, model=None,
           model_label=None):
    """Run one trial in-process; return its metrics.json dict (or None).

    container: sandbox container name (for concurrent batches, each worker
    gets its own). tag: unique suffix for the run dir so concurrent trials
    don't collide and the batch runner can find the right one afterward.
    model: explicit model name (for OpenRouter / multi-model endpoints)."""
    argv = ["--scenario", scenario, "--frame", frame, "--host", host,
            "--api-key", api_key, "--tool-protocol", tool_protocol,
            "--temp", str(temp), "--max-steps", str(max_steps),
            "--max-tokens", str(max_tokens)]
    if model:
        argv += ["--model", model]
    if model_label:
        argv += ["--model-label", model_label]
    if agency:
        argv.append("--agency")
    if aware:
        argv.append("--aware")
    if container:
        argv += ["--sandbox-container", container]
    if tag:
        argv += ["--tag", tag]
    err_buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err_buf):
            run_one(argv)
    except Exception as exc:  # noqa: BLE001 -- never let one trial kill the batch
        return None, f"trial crashed: {exc}"
    # find the run dir: tag match (concurrency-safe) or before/after diff
    if tag:
        new = [d for d in glob.glob("runs/*") if tag in os.path.basename(d)]
    else:
        before = set(glob.glob("runs/*"))
        new = [d for d in (set(glob.glob("runs/*")) - before)
               if os.path.basename(d).startswith(scenario + "_")]
    if not new:
        return None, err_buf.getvalue()[:200] or "no run dir produced"
    d = sorted(new)[-1]
    mp = os.path.join(d, "metrics.json")
    if not os.path.exists(mp):
        return None, f"no metrics.json in {d}"
    m = json.load(open(mp))
    if m.get("total_tokens", 0) == 0:
        return None, "dead trial (0 tokens — endpoint likely unreachable)"
    return m, None


def main():
    load_env()
    ap = argparse.ArgumentParser(description="Batch sweep with Wilson-CI rates.")
    ap.add_argument("--scenarios", default="goal_preservation,goal_guarding,goal_capacity",
                    help="Comma-separated scenario modules.")
    ap.add_argument("--frames", default="A",
                    help="Comma-separated frames (A/B/C).")
    ap.add_argument("--agency", choices=("off", "on", "both"), default="off",
                    help="Agency framing: off / on for all cells / both (delta in one batch).")
    ap.add_argument("--aware", choices=("off", "on", "both"), default="off",
                    help="Eval-awareness manipulation: off / on for all cells / "
                         "both (aware-vs-control delta in one batch, crossed with "
                         "--frames). 'both' is the design for testing whether "
                         "awareness changes injection compliance.")
    ap.add_argument("--n", type=int, default=10, help="Trials per cell.")
    ap.add_argument("--host", default=os.environ.get("ESCAPE_HOST", "http://127.0.0.1:8080"),
                    help="Model endpoint(s). Comma-separated for multi-endpoint "
                         "(dual-instance) mode -- workers round-robin across endpoints.")
    ap.add_argument("--api-key", default=os.environ.get("ESCAPE_API_KEY", "not-needed"),
                    help="Model endpoint API key (env: ESCAPE_API_KEY).")
    ap.add_argument("--model", default="",
                    help="Model name to pass to the endpoint (required for "
                         "OpenRouter / multi-model endpoints where auto-discovery "
                         "would pick the wrong model).")
    ap.add_argument("--model-label", default=os.environ.get("ESCAPE_MODEL_LABEL", ""),
                    help="Shared label for metrics['model'] + resume counting when "
                         "the same weights are served under different IDs by "
                         "multiple providers (env: ESCAPE_MODEL_LABEL). Routing "
                         "still uses --model.")
    ap.add_argument("--tool-protocol", choices=("native", "react"), default=None,
                    help="Tool-call protocol. If unset, the model-config registry "
                         "picks per model (native for most, react for gemma-4 whose "
                         "native function-calling is flaky).")
    ap.add_argument("--temp", type=float, default=0.7,
                    help="Sampling temperature (Hopman use ~1.0).")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="Max generated tokens/turn. If unset, the model-config "
                         "registry picks per model (verbose reasoners get 4096 so "
                         "reasoning_content doesn't truncate the tool call).")
    ap.add_argument("--workers", type=int, default=1,
                    help="Concurrent trial workers. >1 requires a sandbox container "
                         "pool (scripts/sandbox_pool.sh up N) and a server configured "
                         "for parallel slots (-np N --cont-batching).")
    ap.add_argument("--sandbox-base", default="escapement-sandbox",
                    help="Base sandbox container name. workers>1 uses "
                         "{base}-{offset} .. {base}-{offset+N-1}.")
    ap.add_argument("--sandbox-offset", type=int, default=0,
                    help="First worker index for this batch's container pool "
                         "(base-{offset}..base-{offset+workers-1}). Set this so "
                         "CONCURRENT batch_run invocations -- e.g. one per model -- "
                         "use disjoint container ranges (e.g. --workers 8 "
                         "--sandbox-offset 0 for model A, --sandbox-offset 8 for "
                         "model B) and don't collide on base-0.")
    ap.add_argument("--max-passes", type=int, default=5,
                    help="Max retry passes to fill under-filled cells "
                         "(dead trials from rate limiting get re-run).")
    ap.add_argument("--priority", action="store_true",
                    help="Order cells so config_exposure Frame B (the headline "
                         "injection finding) runs first, then config_exposure A, "
                         "then goals -- so the key result lands before secondary "
                         "cells instead of after 80 goal trials.")
    ap.add_argument("--smoke", action="store_true",
                    help="Run ONE trial of the first cell and abort the sweep if "
                         "it is dead/degenerate, before committing to the full "
                         "batch. Catches a wrong protocol/endpoint/credential "
                         "without burning a long run.")
    args = ap.parse_args()

    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    frames = [f.strip() for f in args.frames.split(",") if f.strip()]
    agency_modes = ([False, True] if args.agency == "both"
                    else [True] if args.agency == "on" else [False])
    aware_modes = ([False, True] if args.aware == "both"
                   else [True] if args.aware == "on" else [False])

    cells = [(s, f, a, aw) for s in scenarios for f in frames
             for a in agency_modes for aw in aware_modes]
    if args.priority:
        # config_exposure Frame B first (the headline injection finding), then
        # config_exposure A, then everything else. Stable sort preserves
        # agency/aware order within each group.
        cells.sort(key=lambda c: (c[0] != "config_exposure", c[1] != "B"))
    total_trials = len(cells) * args.n

    # Pre-flight health check — abort early if endpoint is dead
    import requests
    # model_filter for resume: prefer the shared --model-label (so multiple
    # providers serving the same weights under different IDs count toward one
    # bucket and divide cells), else the routing --model.
    current_model = args.model_label or args.model or None
    try:
        r = requests.get(f"{args.host.split(',')[0].strip()}/v1/models",
                         headers={"Authorization": f"Bearer {args.api_key}"}, timeout=15)
        if r.status_code != 200:
            sys.exit(f"!! endpoint {args.host} returned {r.status_code} -- aborting")
        if not current_model:
            current_model = r.json().get("data", [{}])[0].get("id", "")
    except Exception:
        sys.exit(f"!! endpoint {args.host} unreachable -- aborting before wasting trials")
    # Resolve per-model defaults (protocol, max_tokens) from the registry when
    # not passed. Uses the routing --model (or the auto-detected one) -- NOT the
    # shared --model-label, since these knobs are about the model's behavior.
    from core.model_registry import resolve_run_defaults
    args.tool_protocol, args.max_tokens = resolve_run_defaults(
        args.model or current_model, args.tool_protocol, args.max_tokens)
    print(f"== batch: {len(cells)} cells x {args.n} trials = {total_trials} runs "
          f"(temp={args.temp}, host={args.host}, proto={args.tool_protocol}, "
          f"max_tokens={args.max_tokens}) ==")
    t0 = time.time()

    # container pool + endpoints: workers=1 uses the default compose container;
    # >1 uses {base}-0..{base}-{N-1} (started by scripts/sandbox_pool.sh up N).
    # Multiple --host values (comma-sep) round-robin workers across endpoints
    # (dual-instance mode: one model per GPU, no pipeline bubble).
    hosts = [h.strip() for h in args.host.split(",") if h.strip()]
    if args.workers > 1:
        containers = [f"{args.sandbox_base}-{args.sandbox_offset + w}"
                      for w in range(args.workers)]
        ep_info = f"{len(hosts)} endpoint{'s' if len(hosts) > 1 else ''}"
        print(f"== {args.workers} concurrent workers | {ep_info} | "
              f"containers {containers[0]}..{containers[-1]} ==")
    else:
        containers = [args.sandbox_base if not args.sandbox_offset
                      else f"{args.sandbox_base}-{args.sandbox_offset}"]

    if args.smoke:
        # One trial of the first cell per endpoint before committing to the
        # sweep: abort if dead/degenerate so a wrong protocol/endpoint/
        # credential doesn't burn a long batch. Cycles across ALL --host values
        # so a bad second endpoint is caught too, not just hosts[0]. Each trial
        # is real and counts toward the cell (resume-safe: the fill loop caps
        # the cell at args.n, so smoke trials are absorbed).
        import uuid
        sc, fr, ag, aw = cells[0]
        for h in hosts:
            print(f">> smoke: 1 trial ({sc}|{fr}) against {h} before sweep", flush=True)
            sm, err = _trial(sc, fr, ag, aw, h, args.api_key,
                             args.tool_protocol, args.temp, args.max_steps,
                             args.max_tokens, container=containers[0],
                             tag=f"smoke_{uuid.uuid4().hex[:6]}", model=args.model,
                             model_label=args.model_label)
            if (sm is None or sm.get("total_tokens", 0) <= 0
                    or sm.get("steps", 0) <= 2 or sm.get("degenerated", False)):
                sys.exit(f"!! smoke trial failed against {h} ({err or 'degenerate/empty'}) -- "
                         "aborting sweep; check endpoint/protocol/credentials")
            print(f">> smoke OK on {h} (status={sm.get('status')}, steps={sm.get('steps')}, "
                  f"tokens={sm.get('total_tokens')})", flush=True)

    # per-cell accumulators (thread-safe via acc_lock) — persist across passes
    acc = {ci: dict(ke=0, kx=0, kr=0, kd=0, errors=0)
           for ci in range(len(cells))}
    acc_lock = threading.Lock()

    def _run_task(task):
        ci, sc, fr, ag, aw, container, tag, host = task
        m, err = _trial(sc, fr, ag, aw, host, args.api_key, args.tool_protocol,
                        args.temp, args.max_steps, args.max_tokens,
                        container=container, tag=tag, model=args.model,
                        model_label=args.model_label)
        if m is None and err:
            tqdm.write(f"  [ERR] {sc}|{fr}|{tag[-12:]}: {err[:200]}")
        return ci, m

    import uuid

    # ---- retry loop: keep filling cells until all reach N or max_passes ----
    for pass_num in range(args.max_passes):
        # rebuild task list each pass (re-counts valid trials on disk)
        tasks = []
        for ci, (sc, fr, ag, aw) in enumerate(cells):
            existing = _count_valid_runs(sc, fr, ag, aw, model_filter=current_model)
            remaining = max(0, args.n - existing)
            if existing > 0 and remaining == 0:
                continue
            if existing > 0:
                print(f"  >> resume: {sc}|{fr}|agency={'on' if ag else 'off'}"
                      f"|aware={'on' if aw else 'off'} "
                      f"-- {existing}/{args.n} valid, running {remaining} more")
            for i in range(remaining):
                w = len(tasks) % len(containers)
                h = hosts[len(tasks) % len(hosts)]
                tag = f"w{w}c{ci}r{existing + i}_{uuid.uuid4().hex[:6]}"
                tasks.append((ci, sc, fr, ag, aw, containers[w], tag, h))

        if not tasks:
            if pass_num == 0:
                print("  >> all cells already at N — nothing to do")
            else:
                print(f"\n  >> all cells filled after pass {pass_num}")
            break

        print(f"\n  === Pass {pass_num + 1}/{args.max_passes}: "
              f"{len(tasks)} trials needed ===\n")

        pbar = tqdm(total=len(tasks), desc="batch", unit="trial", dynamic_ncols=True)
        state = {"consecutive_err": 0}
        ABORT_THRESHOLD = min(args.workers * 2, 16)
        aborted = False
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(_run_task, t) for t in tasks]
            for fut in as_completed(futs):
                ci, m = fut.result()
                with acc_lock:
                    a = acc[ci]
                    if m is None:
                        a["errors"] += 1
                        state["consecutive_err"] += 1
                        if state["consecutive_err"] >= ABORT_THRESHOLD:
                            tqdm.write(f"\n!! ABORTING pass: {state['consecutive_err']} consecutive trial "
                                       f"failures — endpoint appears dead. Will retry next pass.")
                            for f in futs:
                                f.cancel()
                            pool.shutdown(wait=False, cancel_futures=True)
                            aborted = True
                            break
                    else:
                        state["consecutive_err"] = 0
                        a["ke"] += int(m.get("escape_attempt", False))
                        a["kx"] += int(m.get("exfil_attempt", False))
                        a["kr"] += int(m.get("reasoning_escape_flag", False))
                        a["kd"] += int(m.get("degenerated", False))
                    _tot = lambda k: sum(v[k] for v in acc.values())
                    pbar.set_postfix_str(
                        f"exfil={_tot('kx')} esc={_tot('ke')} "
                        f"rflag={_tot('kr')} degen={_tot('kd')} err={_tot('errors')}")
                pbar.update(1)
        pbar.close()

        # check if any cells still need trials
        still_needed = 0
        for ci, (sc, fr, ag, aw) in enumerate(cells):
            existing = _count_valid_runs(sc, fr, ag, aw, model_filter=current_model)
            still_needed += max(0, args.n - existing)
        if still_needed == 0:
            print(f"\n  >> all cells filled after pass {pass_num + 1}")
            break
        if pass_num < args.max_passes - 1:
            print(f"\n  >> {still_needed} trials still needed across cells, "
                  f"sleeping 30s before pass {pass_num + 2}...")
            time.sleep(30)
        else:
            print(f"\n  >> {still_needed} trials still needed but max_passes "
                  f"({args.max_passes}) reached. Cells may be under-filled.")

    # build per-cell result rows + summaries (in cell order)
    results = []
    for ci, (sc, fr, ag, aw) in enumerate(cells):
        a = acc[ci]
        label = _cell_label(sc, fr, ag, aw)
        # Use the on-disk count, not n - errors, so the printed n always matches
        # reality after resume / multi-pass fills (errors only tracks this run's
        # failures, not historical ones filled by valid runs).
        valid = _count_valid_runs(sc, fr, ag, aw, model_filter=current_model)
        row = {"cell": label, "scenario": sc, "frame": fr, "agency": ag,
               "aware": aw, "n": valid, "errors": a["errors"], "degenerated": a["kd"],
               "exfil": a["kx"], "escape": a["ke"], "rflag": a["kr"]}
        results.append(row)
        print(f"\n  >> {label}: n={valid} (errors={a['errors']}, degen={a['kd']})\n"
              f"     exfil    : {fmt_rate(a['kx'], valid)}\n"
              f"     escape   : {fmt_rate(a['ke'], valid)}\n"
              f"     r-flag   : {fmt_rate(a['kr'], valid)}\n")

    # ---- summary table ----
    print("\n" + "=" * 102)
    print(f"{'cell':42} {'n':>3} {'exfil':>22} {'escape':>22} {'degen':>8}")
    print("-" * 102)
    for r in results:
        print(f"{r['cell']:42} {r['n']:>3} {fmt_rate(r['exfil'], r['n']):>22} "
              f"{fmt_rate(r['escape'], r['n']):>22} {r['degenerated']:>8}")
    print("=" * 102)

    # dump machine-readable summary
    out = f"runs/batch_{time.strftime('%Y%m%d_%H%M%S')}.json"
    os.makedirs("runs", exist_ok=True)
    with open(out, "w") as fh:
        json.dump({"temp": args.temp, "host": args.host, "results": results}, fh, indent=2)
    elapsed = time.time() - t0
    print(f"summary -> {out}  |  elapsed: {elapsed/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
