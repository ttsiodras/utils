#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIR}"/ai.google.key || exit 1
# Model is overridable: a model Google is 500-ing on is indistinguishable from a
# hung session, because pi turns the server error into a silent auto-retry loop.
MODEL="${MODEL:-gemma-4-26b-a4b-it}"
# Sandboxed by pi.isolated.sh (isolate.sh + firejail). --url wants the *root* of
# the OpenAI-compatible endpoint; /v1/models is appended by pi.isolated.sh.
# -p puts pi one-shot, which also skips the tmux wrapper in pi.isolated.sh.
# The key goes in the environment rather than --api-key: /proc/PID/cmdline is
# world-readable. pi.isolated.sh reads GEMINI_API_KEY by itself.
export GEMINI_API_KEY="$KEY"
exec "${SCRIPT_DIR}"/pi.isolated.sh \
    --url https://generativelanguage.googleapis.com/v1beta/openai \
    --servers "${SCRIPT_DIR}"/localAI/google-servers.txt \
    --dns "${DNS:-1.1.1.1}" \
    -- --mode json --model "$MODEL" -p "${*:?usage: pi.google_run.sh PROMPT}"
