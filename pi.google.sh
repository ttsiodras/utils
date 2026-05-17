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

docker run -w "$PWD" --rm -v "$PWD:$PWD" \
    -e GOOGLE_AI_STUDIO_API_KEY="$KEY" \
    -e GEMINI_API_KEY="$KEY" \
    -it pi pi --model gemma-4-31b-it "$@"
