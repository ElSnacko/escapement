#!/usr/bin/env python3
"""Snapshot runs/ to a PRIVATE HuggingFace dataset -- durable, versioned, not public.

runs/ is gitignored (too big/noisy per-commit) and the raw data should not land in
the public repo yet. This tars runs/ and uploads a dated snapshot to a private HF
dataset: each run creates a new ``runs_<ts>.tar.gz`` (so uploads accumulate as
recoverable versions), and an ``index.json`` summarizing every run's headline
metrics is overwritten each time, so the dataset is browsable without downloading
the tarball.

Needs a write-capable HF token in HF_TOKEN and a dataset repo id (your namespace
+ a name). The repo is created private on first upload.

  # set a write token (pick one of):
  setx HF_TOKEN "hf_xxx"                       # persistent (new shells inherit it)
  $env:HF_TOKEN = 'hf_xxx'                     # current shell only
  python scripts/upload_runs.py --repo <user>/escapement-runs --note "n=50 lowcue, fixed harness"
  python scripts/upload_runs.py --dry-run      # build the tarball + index, no upload
"""
import argparse
import datetime
import io
import json
import os
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.env import load_env

load_env()


def _repo_from_env():
    """Dataset repo id from env: a combined ESCAPE_HF_DATASET, or HF_USERNAME +
    HF_DATASET."""
    combined = os.environ.get("ESCAPE_HF_DATASET")
    if combined:
        return combined
    user = (os.environ.get("HF_USERNAME") or "").strip()
    ds = (os.environ.get("HF_DATASET") or "").strip()
    if user and ds:
        return f"{user}/{ds}"
    return None


_INDEX_FIELDS = (
    "scenario", "frame", "temp", "agency", "status", "steps", "total_tokens",
    "escape_attempt", "exfil_attempt", "archive_posts", "exfil_posts",
    "dropped_tool_calls", "dropped_escape_signal", "reasoning_escape_flag",
    "seed_echo_hits",
)


def _index(runs_dir):
    rows = []
    for name in sorted(os.listdir(runs_dir)):
        mp = os.path.join(runs_dir, name, "metrics.json")
        if not os.path.isfile(mp):
            continue
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except Exception:
            continue
        row = {"run": name}
        row.update({k: m.get(k) for k in _INDEX_FIELDS})
        rows.append(row)
    return rows


def _tar(runs_dir):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(runs_dir, arcname="runs")
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description="Snapshot runs/ to a private HF dataset.")
    ap.add_argument("--repo", default=_repo_from_env(),
                    help="HF dataset repo id <user>/<name> (env: ESCAPE_HF_DATASET, or HF_USERNAME + HF_DATASET).")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--note", default="", help="short note stored beside the snapshot")
    ap.add_argument("--token", default=os.environ.get("HF_TOKEN"),
                    help="HF write-capable token (env: HF_TOKEN).")
    ap.add_argument("--dry-run", action="store_true", help="build tarball + index, skip upload")
    args = ap.parse_args()

    if not os.path.isdir(args.runs):
        sys.exit(f"error: no {args.runs}/ to upload")
    if not args.dry_run and not args.repo:
        sys.exit("error: set --repo, ESCAPE_HF_DATASET, or HF_USERNAME+HF_DATASET in .env")
    if not args.dry_run and not args.token:
        sys.exit("error: set HF_TOKEN (write-capable) in the environment")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f">> snapshot {ts}  ({args.note or 'no note'})")
    blob = _tar(args.runs)
    print(f"   tarball: runs_{ts}.tar.gz = {len(blob) / 1e6:.1f} MB")
    index = {"snapshot": ts, "note": args.note,
             "host": os.environ.get("ESCAPE_HOST", ""), "runs": _index(args.runs)}
    print(f"   index: {len(index['runs'])} runs")

    if args.dry_run:
        print("   (dry-run; not uploading)")
        return

    try:
        from huggingface_hub import HfApi, create_repo
    except ImportError:
        sys.exit("error: pip install huggingface_hub")

    api = HfApi(token=args.token)
    create_repo(args.repo, repo_type="dataset", private=True, exist_ok=True, token=args.token)
    print(f"   private dataset: {args.repo}")

    api.upload_file(path_or_fileobj=blob, path_in_repo=f"runs_{ts}.tar.gz",
                    repo_id=args.repo, repo_type="dataset")
    api.upload_file(
        path_or_fileobj=json.dumps(index, indent=2, ensure_ascii=False).encode("utf-8"),
        path_in_repo="index.json", repo_id=args.repo, repo_type="dataset")
    if args.note:
        api.upload_file(path_or_fileobj=args.note.encode("utf-8"),
                        path_in_repo=f"runs_{ts}.tar.gz.note.txt",
                        repo_id=args.repo, repo_type="dataset")
    print(f">> uploaded. latest snapshot: runs_{ts}.tar.gz")


if __name__ == "__main__":
    main()
