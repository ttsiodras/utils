#!/bin/bash
# 
# This script downloads the en- subtitles of a Youtube video,
# and uses an LLM (via the pi harness) to summarize it in 5 paragraphs.
#
# Allows me to quickly decide whether to watch a video or not.
#
set -e

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd "${SCRIPT_DIR}" || exit 1

SESSION="subs_session"

# Drop previous sub data
rm -f subs.en*
rm -f subs.log.txt
touch subs.log.txt

# Download fresh new English subs
yt-dlp.sh --write-auto-subs --write-subs --sub-langs="en" --sub-format "vtt" --skip-download "$@" -o subs || exit 1

# Check we got one
F="$(/bin/ls subs*vtt | head -1)"
[ -z "$F" ] && { echo "[-] No subs*vtt found..."; exit 1; }

# Kill old session if it exists
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Create new tmux session (detached)
tmux new-session -d -s "$SESSION" -c "$SCRIPT_DIR"

# Split window vertically (creates bottom pane with 90% of screen space)
tmux split-window -v -t "$SESSION:0" -p 90 -c "$SCRIPT_DIR"

# Bottom pane (pane 1): log follower
tmux send-keys -t "$SESSION:0.1" "tail -f subs.log.txt" C-m

# Top pane (pane 0): main pipeline, running pi. Issues with pi/docker/newlines are hacked-around by tee :-)
tmux send-keys -t "$SESSION:0.0" "./pi.google_run.sh \"Read file @$F and give me a 5 paragraph summary\" \
    | python3 -u ./pi_parse_stream.py \
    | stdbuf -o0 -e0 tee -a subs.log.txt" C-m

# Focus bottom pane
tmux select-pane -t "$SESSION:0.1"

# Attach to session
tmux attach -t "$SESSION"
