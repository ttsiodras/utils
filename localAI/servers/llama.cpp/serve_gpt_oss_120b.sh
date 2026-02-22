#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
. "${SCRIPT_DIR}"/common.sh
llama-server "${COMMON_OPTS}" \
    --ctx-size 0 \
    -m ~/.cache/llama.cpp/bartowski_openai_gpt-oss-120b-GGUF_openai_gpt-oss-120b-Q6_K_openai_gpt-oss-120b-Q6_K-00001-of-00002.gguf
    # -hf bartowski/openai_gpt-oss-120b-GGUF:Q6_K
