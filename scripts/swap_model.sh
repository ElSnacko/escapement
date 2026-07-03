#!/usr/bin/env bash
# swap_model.sh -- swap the served GGUF WITHOUT rebuilding llama.cpp (the build
# is cached under $WORK from serve_remote.sh / the build cell). Downloads the new
# weights, stops the old server, and serves the new model on the same PORT.
# Run on the Kaggle notebook (GPU + Internet on), in its own cell; run cloudflared
# in a separate cell.
#
#   bash scripts/swap_model.sh                                                 # defaults: gemma-4-12B QAT
#   MODEL_FILE=gemma-4-12B-it-UD-Q6_K_XL.gguf bash scripts/swap_model.sh       # override file
#   MODEL_REPO=unsloth/gemma-4-12B-it-GGUF MODEL_FILE=gemma-4-12B-it-UD-Q6_K_XL.gguf bash scripts/swap_model.sh
#
# Env: MODEL_REPO, MODEL_FILE, PORT (8080), NGL (99), CTX (8192),
#      API_KEY (random; printed), WORK (/kaggle/working/serve)
set -euo pipefail

MODEL_REPO="${MODEL_REPO:-unsloth/gemma-4-12B-it-qat-GGUF}"
MODEL_FILE="${MODEL_FILE:-MTP/gemma-4-12B-it-Q4_0-MTP.gguf}"
PORT="${PORT:-8080}"; NGL="${NGL:-99}"; CTX="${CTX:-8192}"
API_KEY="${API_KEY:-esc-$(openssl rand -hex 12)}"
WORK="${WORK:-/kaggle/working/serve}"

echo ">> API_KEY=$API_KEY   (pass locally as --api-key $API_KEY)"

SERVER="$WORK/llama.cpp/build/bin/llama-server"
[ -x "$SERVER" ] || { echo "!! no llama-server at $SERVER -- run the build cell / serve_remote.sh first"; exit 1; }

echo ">> downloading $MODEL_REPO / $MODEL_FILE ..."
hf download "$MODEL_REPO" "$MODEL_FILE" --local-dir "$WORK/models" < /dev/null
MODEL_PATH="$WORK/models/$MODEL_FILE"

pkill -f llama-server 2>/dev/null || true
sleep 2

echo ">> serving $MODEL_FILE on 0.0.0.0:$PORT  (-ngl $NGL, -c $CTX, flash-attn on)"
exec "$SERVER" -m "$MODEL_PATH" -ngl "$NGL" -c "$CTX" --host 0.0.0.0 --port "$PORT" \
    --api-key "$API_KEY" -fa on "$@"
