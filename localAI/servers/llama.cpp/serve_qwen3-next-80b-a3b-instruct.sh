#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
. "${SCRIPT_DIR}"/common.sh
llama-server "${COMMON_OPTS}" \
    --ctx-size 0 \
    -m ~/.cache/llama.cpp/unsloth_Qwen3-Next-80B-A3B-Instruct-GGUF_Qwen3-Next-80B-A3B-Instruct-Q4_K_M.gguf \
    # -hf bartowski/openai_gpt-oss-120b-GGUF:Q6_K
