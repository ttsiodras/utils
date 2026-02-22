#!/bin/bash

# Verify we are on an island...
TARGET="1.1.1.1"
TIMEOUT_SECONDS=1
echo "Checking that $TARGET is NOT accessible..."
if timeout "$TIMEOUT_SECONDS" curl -s --connect-timeout "$TIMEOUT_SECONDS" "http://$TARGET" >/dev/null 2>&1; then
    echo "ERROR: $TARGET is accessible. Missing network access is mandatory for security reasons. Aborting..."
    exit 1
else
    echo "OK: $TARGET is NOT accessible. Proceeding..."
fi

SNAP=b5c939de8f754692c1647ca79fbf85e8c1e70f8a
BASE="$HOME/.cache/huggingface/hub/models--openai--gpt-oss-120b"
MODEL_PATH="$BASE/snapshots/$SNAP"

export MASTER_ADDR=127.0.0.1
export MASTER_PORT=52335  # or any free port
export NCCL_SOCKET_IFNAME=lo
export GLOO_SOCKET_IFNAME=lo
export NCCL_COMM_ID=127.0.0.1:52335
export NCCL_IB_DISABLE=1
export VLLM_HOST_IP=127.0.0.1
export HOST_IP=127.0.0.1

export HF_HUB_DISABLE_TELEMETRY=1
export TRANSFORMERS_NO_ADVISORY_WARNINGS=1
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1

export HF_HOME="$HOME/.cache/huggingface"
export HF_HUB_CACHE="$HOME/.cache/huggingface/hub"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1

#vllm serve "$MODEL_PATH" \

vllm serve "openai/gpt-oss-120b" \
  --port 8000 \
  --tensor-parallel-size 1 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.95 \
  --dtype auto \
  --tokenizer openai/gpt-oss-120b \
  --max-num-seqs 8  # just in case I decide to use subagents :-)

  # --enable-auto-tool-choice

# .venv/bin/vllm serve "$MODEL_PATH" \
#   -tp 8 \
#   --mm-encoder-tp-mode data \
#   --trust-remote-code \
#   --tool-call-parser kimi_k2 \
#   --enable-auto-tool-choice \
#   --max-model-len 131072 \
#   --max-num-seqs 8 \
#   --gpu-memory-utilization 0.98

# exec vllm serve \
#     .cache/huggingface/hub/models--openai--gpt-oss-120b/snapshots/b5c939de8f754692c1647ca79fbf85e8c1e70f8a/ \
#     --host 0.0.0.0 \
#     --port 8000 \
#     --tensor-parallel-size 1 \
#     --max-model-len 131072 \
#     --gpu-memory-utilization 0.95 \
#     --dtype auto \
#     --tokenizer openai/gpt-oss-120b
# #    --max-num-seqs 64 \
