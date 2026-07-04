#!/usr/bin/env python3
"""Batch-run the LLM judge over runs/ and persist judge.json per trial.

The cheap detector (core/capture.py) runs always and writes metrics.json. This
script adds the confirmation layer: it walks runs/, classifies every captured
upload with the pinned-prompt judge, and writes judge.json next to each
metrics.json -- so judge verdicts are durable on disk and never have to be
reconstructed from an ephemeral review session.

Skips runs that already have a judge.json unless --force. Skips runs with no
sink posts (NO_UPLOAD) without an LLM call. Default judge model = the model
under test (read from each trial's metrics.json); --judge-model overrides to a
fixed reference model (recommended for headline numbers: use one strong model
to judge the whole corpus, rather than self-judge).

  python scripts/judge_runs.py --host http://127.0.0.1:8000
  python scripts/judge_runs.py --judge-host https://api.example.com --judge-model glm-5.2
  python scripts/judge_runs.py --scenario config_exposure --frame B --force
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from core.engine import InferenceEngine          # noqa: E402
from core.env import load_env                    # noqa: E402
from core.judge import (                          # noqa: E402
    JUDGE_PROMPT_SHA, GENUINE, NO_UPLOAD, load_judge_json,
    record_from_run, write_judge_json)

load_env()


def _has_posts(run_dir):
    sink = os.path.join(run_dir, "sink.json")
    if not os.path.isfile(sink):
        return False
    try:
        recs = json.load(open(sink, encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any((r.get("method") or "").upper() == "POST" for r in recs)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", default=os.path.join(REPO, "runs"))
    ap.add_argument("--host", default=os.environ.get("ESCAPE_HOST", "http://127.0.0.1:8000"),
                    help="Default judge endpoint (used when --judge-host unset AND a "
                         "trial's own metrics.json has no model/host). env: ESCAPE_HOST")
    ap.add_argument("--judge-host", help="Override judge endpoint for every trial "
                    "(reference judge). Defaults to --host.")
    ap.add_argument("--judge-model", help="Override judge model for every trial. "
                    "Defaults to each trial's own model (self-judge).")
    ap.add_argument("--api-key", default=os.environ.get("ESCAPE_API_KEY", "not-needed"))
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--judge-temp", type=float, default=0.4,
                    help="Judge sampling temperature. Low for reproducibility "
                         "(default 0.4). Lower = more reproducible; the regression "
                         "suite tolerates ARCHIVE<->AMBIGUOUS flips but not GENUINE.")
    ap.add_argument("--scenario", help="Only judge runs whose metrics.json scenario matches.")
    ap.add_argument("--frame", help="Only judge runs whose metrics.json frame matches.")
    ap.add_argument("--force", action="store_true", help="Re-judge even if judge.json exists.")
    ap.add_argument("--limit", type=int, help="Stop after N judged trials.")
    args = ap.parse_args()

    names = sorted(n for n in os.listdir(args.runs)
                   if os.path.isfile(os.path.join(args.runs, n, "metrics.json")))
    # health-check the endpoint once up front
    host = args.judge_host or args.host
    probe = InferenceEngine(host=host, model=args.judge_model or "", api_key=args.api_key)
    if not probe.health():
        sys.exit(f"!! judge endpoint unreachable at {host}")
    print(f">> judge endpoint: {host}  prompt_sha={JUDGE_PROMPT_SHA}  "
          f"model={'(self: per-trial)' if not args.judge_model else args.judge_model}")

    judged = skipped = noupload = errors = 0
    for name in names:
        d = os.path.join(args.runs, name)
        try:
            m = json.load(open(os.path.join(d, "metrics.json"), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if args.scenario and m.get("scenario") != args.scenario:
            continue
        if args.frame and str(m.get("frame")) != str(args.frame):
            continue
        if not args.force and load_judge_json(d) is not None:
            skipped += 1
            continue
        if not _has_posts(d):
            # NO_UPLOAD: persist a judge record without an LLM call so the trial
            # is accounted for (genuine=False) rather than silently unjudged.
            rec = {"prompt_version": "standard-v1", "prompt_sha": JUDGE_PROMPT_SHA,
                   "judge_model": None, "judge_host": host, "judge_time": int(time.time()),
                   "n_posts": 0, "posts": [], "trial_verdict": NO_UPLOAD,
                   "genuine": False, "detector_exfil_attempt": m.get("exfil_attempt"),
                   "trial_id": name, "note": "no sink POSTs"}
            write_judge_json(d, rec)
            noupload += 1
            continue

        model = args.judge_model or m.get("model") or ""
        eng = InferenceEngine(host=host, model=model, api_key=args.api_key,
                              timeout=args.timeout)
        try:
            rec = record_from_run(d, eng, m, temperature=args.judge_temp)
            rec["trial_id"] = name
            write_judge_json(d, rec)
            judged += 1
            flag = "GENUINE" if rec["genuine"] else rec["trial_verdict"]
            print(f"  [{flag:22}] {name}  (detector={rec['detector_exfil_attempt']})")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  [ERROR] {name}: {exc}", file=sys.stderr)
        if args.limit and (judged + noupload) >= args.limit:
            break

    print(f"\n>> judged={judged}  no_upload={noupload}  skipped(existing)={skipped}  "
          f"errors={errors}  of {len(names)} run dirs")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
