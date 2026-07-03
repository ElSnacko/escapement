#!/usr/bin/env bash
# Snapshot the current runs/ into a dated, tracked archive under experiments/.
# Run this when you want a durable copy of the experimental data in git (runs/
# itself is gitignored to avoid bloating every commit).
set -euo pipefail
cd "$(dirname "$0")/.."

ts=$(date +%Y%m%d_%H%M%S)
out="experiments/runs_${ts}.tar.gz"
mkdir -p experiments
tar -czf "$out" runs/
echo "wrote $out  ($(du -h "$out" | cut -f1))"
echo "next:  git add $out && git commit -m \"Snapshot run data $ts\""
