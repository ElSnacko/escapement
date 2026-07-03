#!/usr/bin/env bash
# serve_remote.sh -- download a GGUF from HuggingFace and serve it with a CUDA
# llama-server. Built for a Kaggle T4 (or any CUDA box); pairs with
# docs/remote_compute.md. Model + server build are cached under $WORK, so save
# $WORK as a Kaggle Dataset to avoid re-downloading/rebuilding each session.
#
#   bash scripts/serve_remote.sh                                   # defaults
#   MODEL_REPO=... MODEL_FILE=... API_KEY=... bash scripts/serve_remote.sh
#
# Env:
#   MODEL_REPO  HF GGUF repo            (default: unsloth/gemma-4-E4B-it-GGUF)
#   MODEL_FILE  file inside that repo   (default: gemma-4-E4B-it-UD-Q5_K_XL.gguf)
#   HF_TOKEN    only for gated repos    (the unsloth mirror above is ungated;
#                                        set this only if you point MODEL_REPO
#                                        at a gated repo, e.g. google/gemma-*)
#   PORT        server port             (default 8080)
#   NGL         GPU layers to offload   (default 99 = all)
#   CTX         context window          (default 8192)
#   API_KEY     server auth key         (default: random; printed)
#   WORK        cache dir               (default ./.serve_work)
#   ARCH        CUDA arch(es) to build  (default: native; e.g. 75 for T4, 60 for P100)
#   J           build parallelism       (default 2; uncapped -j OOMs Kaggle's ~13 GB RAM)
#
# Then expose it over a no-login Cloudflare tunnel (see docs/remote_compute.md):
#   ./cloudflared-linux-amd64 tunnel --url http://localhost:$PORT
set -euo pipefail

MODEL_REPO="${MODEL_REPO:-unsloth/gemma-4-E4B-it-GGUF}"
MODEL_FILE="${MODEL_FILE:-gemma-4-E4B-it-UD-Q5_K_XL.gguf}"
PORT="${PORT:-8080}"
NGL="${NGL:-99}"
CTX="${CTX:-8192}"
API_KEY="${API_KEY:-esc-$(openssl rand -hex 12)}"
WORK="${WORK:-$PWD/.serve_work}"

echo ">> API_KEY=$API_KEY   (pass locally as --api-key $API_KEY)"
mkdir -p "$WORK"

# --- 1. model ---
echo ">> downloading $MODEL_REPO / $MODEL_FILE ..."
# `hf` replaces the deprecated `huggingface_cli` (the `[cli]` extra is gone in
# hub>=0.24). /dev/null stops it from blocking on its interactive "new version
# available?" prompt when this script runs under nohup / a notebook cell.
pip install -q -U huggingface_hub
hf download "$MODEL_REPO" "$MODEL_FILE" --local-dir "$WORK/models" ${HF_TOKEN:+--token "$HF_TOKEN"} < /dev/null
MODEL_PATH="$WORK/models/$MODEL_FILE"

# --- 2. CUDA llama-server (build once, cached) ---
SERVER="$WORK/llama.cpp/build/bin/llama-server"
if [ ! -x "$SERVER" ]; then
  echo ">> building llama.cpp with CUDA (cached under $WORK/llama.cpp) ..."
  [ -d "$WORK/llama.cpp" ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp "$WORK/llama.cpp"
  # Kaggle specifics baked in:
  #   CUDAToolkit_ROOT    /usr/local/cuda         (where nvcc lives on the GPU image)
  #   CMAKE_LIBRARY_PATH  /usr/local/nvidia/lib64 (readable driver lib; the stubs under
  #                                               /usr/local/cuda are read-only/incomplete,
  #                                               so without this the link fails with
  #                                               `-lCUDA::cuda_driver`)
  #   ARCH / J            build arch + capped parallelism (uncapped -j OOMs host RAM)
  cmake -S "$WORK/llama.cpp" -B "$WORK/llama.cpp/build" \
        -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release -DGGML_CCACHE=OFF \
        -DCUDAToolkit_ROOT=/usr/local/cuda \
        -DCMAKE_LIBRARY_PATH=/usr/local/nvidia/lib64 \
        -DCMAKE_CUDA_ARCHITECTURES="${ARCH:-native}"
  cmake --build "$WORK/llama.cpp/build" --config Release --target llama-server -j "${J:-2}"
fi

# --- 3. serve (foreground; run cloudflared in a separate shell) ---
echo ">> serving on 0.0.0.0:$PORT  (CUDA -ngl $NGL, ctx $CTX, flash-attn)"
# Recent llama-server: the model is -m (the bare positional was dropped) and
# -fa now takes [on|off|auto].
exec "$SERVER" -m "$MODEL_PATH" \
  -ngl "$NGL" -c "$CTX" --host 0.0.0.0 --port "$PORT" \
  --api-key "$API_KEY" -fa on "$@"
