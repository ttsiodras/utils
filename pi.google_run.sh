#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIR}"/ai.google.key || exit 1
docker run -w "$PWD" --rm -v "$PWD:$PWD" \
    -e NODE_NO_READLINE=1 \
    -e FORCE_COLOR=1 \
    -e GOOGLE_AI_STUDIO_API_KEY="$KEY" \
    -e GEMINI_API_KEY="$KEY" \
    -it pi stdbuf -o0 -e0 pi --mode json --model gemma-4-31b-it -p "$@"
