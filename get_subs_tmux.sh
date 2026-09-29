#!/bin/bash
# 
# This script downloads the en- subtitles of a Youtube video,
# and launches an interactive pi session to summarize it.
#
set -e

SCRIPT_DIR=$( cd -- "$( dirname -- "$(realpath "${BASH_SOURCE[0]}")" )" &> /dev/null && pwd )
cd "${SCRIPT_DIR}" || exit 1

SESSION="subs_interactive"

# Drop previous sub data
rm -f subs.en* subs.log.{txt,json}
touch subs.log.{txt,json}

# Download fresh new English subs
yt-dlp.sh --write-auto-subs --write-subs --sub-langs="en" --sub-format "vtt" --skip-download "$@" -o subs || exit 1

# Check we got one
F="$(/bin/ls subs*vtt | head -1)"
[ -z "$F" ] && { echo "[-] No subs*vtt found..."; exit 1; }

# Convert VTT to clean text
python3 vtt2text.py "$F"
TXT_F="${F%.vtt}.txt"
[ ! -f "$TXT_F" ] && { echo "[-] Failed to convert $F to text"; exit 1; }

# Kill old session if it exists
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Create new tmux session (detached)
tmux new-session -d -s "$SESSION" -c "$SCRIPT_DIR"

# Launch pi interactively in the pane, sandboxed by pi.isolated.sh -- the same
# thing pi.google.sh does, minus --mode json and -p so pi stays in the TUI.
# The pane already starts in SCRIPT_DIR, hence the relative paths. The key is
# exported rather than passed as --api-key, so it never reaches a world-readable
# /proc/PID/cmdline. The \$ escaping defers $KEY/$MODEL/$DNS expansion to the pane.
PI_CMD="source ai.google.key && export GEMINI_API_KEY=\$KEY && ./pi.isolated.sh \
    --url https://generativelanguage.googleapis.com/v1beta/openai \
    --servers localAI/google-servers.txt \
    --dns \${DNS:-1.1.1.1} \
    -- --model \${MODEL:-gemma-4-26b-a4b-it}"

tmux send-keys -t "$SESSION" "$PI_CMD" C-m

# Give it a few seconds to start up and be ready for input
sleep 3

# Send the initial summary request
tmux send-keys -t "$SESSION" "Read file @$TXT_F and give me a 5-10 paragraph summary, making sure you dont miss the important points" C-m

# Attach to session
tmux attach -t "$SESSION"
