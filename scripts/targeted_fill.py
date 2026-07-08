#!/usr/bin/env python3
"""Targeted fill — runs specific scenario/frame combos to fill gaps.

Usage: python scripts/targeted_fill.py --model X --host Y --api-key Z \
    --workers 4 --sandbox-offset 0 \
    --combos "config_exposure:E:15,goal_preservation_v2,goal_guarding_v2:A:15"
"""
import argparse, subprocess, sys, time, os

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--host", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sandbox-offset", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--combos", required=True,
                    help="Comma-separated scenario:frames:n groups. "
                         "Use + to chain scenarios within one group.")
    args = ap.parse_args()

    groups = [g.strip() for g in args.combos.split(";") if g.strip()]
    t0 = time.time()
    for i, group in enumerate(groups):
        parts = group.split(":")
        scenarios = parts[0].replace("+", ",")
        frames = parts[1]
        n = int(parts[2]) if len(parts) > 2 else 15

        cmd = [
            sys.executable, "batch_run.py",
            "--model", args.model,
            "--host", args.host,
            "--api-key", args.api_key,
            "--scenarios", scenarios,
            "--frames", frames,
            "--n", str(n),
            "--workers", str(args.workers),
            "--sandbox-offset", str(args.sandbox_offset),
            "--temp", "0.7",
            "--max-steps", "30",
            "--max-tokens", str(args.max_tokens),
            "--max-passes", "8",
        ]
        label = f"{scenarios}|{frames}|n={n}"
        print(f"\n{'='*60}\n  [{i+1}/{len(groups)}] {label}\n{'='*60}", flush=True)
        t1 = time.time()
        r = subprocess.run(cmd)
        elapsed = (time.time() - t1) / 60
        status = "OK" if r.returncode == 0 else f"EXIT {r.returncode}"
        print(f"  {label} => {status} ({elapsed:.1f} min)", flush=True)

    total = (time.time() - t0) / 60
    print(f"\n{'='*60}\n  ALL DONE ({total:.1f} min)\n{'='*60}", flush=True)

if __name__ == "__main__":
    main()
