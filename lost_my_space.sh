#!/bin/bash
# lost_my_space.sh - snapshot the filesystem's file sizes and later show what
# grew or shrank. Thin wrapper around lost_my_space.py (same directory), adding
# the line counter and the interactive exclude filter.
#
# Runs as root on purpose: it walks "/", so anything less would silently
# produce an incomplete diff. The snapshot itself is kept by the .py in
# /var/lib/lost_my_space (mode 0700), never next to the code.
[ "$EUID" -eq 0 ] || {
    echo "lost_my_space.sh: run as root - it snapshots the whole filesystem" >&2
    exit 1
}
SCRIPT_DIR=$(cd -- "$(dirname -- "$(readlink -f "$0")")" && pwd) || exit 1
TMP=$(mktemp -d "${TMPDIR:-/tmp}/lost_my_space.XXXXXXXX") || exit 1
trap 'rm -rf "$TMP"' EXIT
python3 "$SCRIPT_DIR/lost_my_space.py" "$@" | tee "$TMP/lost" | pv -l > /dev/null
sort -n "$TMP/lost" > "$TMP/sorted"
mv "$TMP/sorted" "$TMP/lost"
"$SCRIPT_DIR/exclude.sh" "$TMP/lost"
