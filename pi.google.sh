#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# No longer necessary, xterm bug fixed.
#
# if [ -z "$KITTY_PID" ]; then
#     echo "[x] You are not inside kitty — pi depends on the Kitty protocol."
#     read -rp "[-] Shall I launch kitty and run pi there? [Y/n] " ANS
#     if [ "$ANS" = "n" ] || [ "$ANS" = "N" ]; then
#         echo "[-] Aborting."
#         exit 1
#     else
#         kitty bash "$0" "$@" &
#         exit 0
#     fi
# fi

source "${SCRIPT_DIR}"/ai.google.key || exit 1

# Model is overridable: a model Google is 500-ing on is indistinguishable from a
# hung session, because pi turns the server error into a silent auto-retry loop.
MODEL="${MODEL:-gemma-4-26b-a4b-it}"

# Sandboxed by pi.isolated.sh (isolate.sh + firejail): $HOME read-only, only $PWD
# writable, and the only host reachable off-box is the one listed in
# localAI/google-servers.txt. --url wants the *root* of the OpenAI-compatible
# endpoint -- pi.isolated.sh appends /v1/models itself. The key goes in the
# environment, not in --api-key: /proc/PID/cmdline is world-readable, so an option
# would expose it for the lifetime of the session. pi.isolated.sh picks up
# GEMINI_API_KEY on its own.
export GEMINI_API_KEY="$KEY"
exec "${SCRIPT_DIR}"/pi.isolated.sh \
    --url https://generativelanguage.googleapis.com/v1beta/openai \
    --servers "${SCRIPT_DIR}"/localAI/google-servers.txt \
    --dns "${DNS:-1.1.1.1}" \
    -- --model "$MODEL" "$@"
