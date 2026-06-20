#!/bin/bash
# 
# This script downloads the en- subtitles of a Youtube video,
# and launches an interactive pi session to summarize it.
#
set -e

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
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

# Launch pi interactively in the pane.
# We mirror the docker configuration from pi.google_run.sh but remove --mode json and -p
# to enter the interactive TUI mode.
PI_CMD="source ai.google.key && \
    docker run -w \$PWD --rm -v \$PWD:\$PWD \
    -e NODE_NO_READLINE=1 -e FORCE_COLOR=1 \
    -e GOOGLE_AI_STUDIO_API_KEY=\$KEY -e GEMINI_API_KEY=\$KEY \
    -it pi pi --model gemma-4-31b-it"

tmux send-keys -t "$SESSION" "$PI_CMD" C-m

# Give it a few seconds to start up and be ready for input
sleep 3

# Send the initial summary request
tmux send-keys -t "$SESSION" "Read file @$TXT_F and give me a 5-10 paragraph summary, making sure you dont miss the important points" C-m

# Attach to session
tmux attach -t "$SESSION"
