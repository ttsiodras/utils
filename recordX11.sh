#!/bin/bash
#
# Lossless X11 screen capture: x264 at -qp 0 (frames come back bit-identical),
# muxed into Matroska.
#
#   recordX11.sh [output.mkv]
#
# Environment overrides:
#   SIZE   grab geometry, e.g. 1920x1080   (default: autodetected via xdpyinfo)
#   FPS    frame rate                      (default: 25)
#   PREROLL  seconds to wait before start  (default: 2, time to focus a window)
#
# Needs: X11 (not Wayland), ffmpeg built with x11grab, x11-utils for xdpyinfo.
#
set -e

OUT="${1:-/tmp/screen.$(date +%Y%m%d-%H%M%S).mkv}"
FPS="${FPS:-25}"
PREROLL="${PREROLL:-2}"

DISPLAY="${DISPLAY:-:0.0}"
# x11grab wants display.screen - and tolerates the +x,y offset suffix as-is.
GRAB="$DISPLAY"
case "$GRAB" in
    *.*|*+*) : ;;                                  # already has .screen or +offset
    *)       GRAB="$GRAB.0" ;;
esac

if [ -z "$SIZE" ]; then
    SIZE=$(xdpyinfo -display "$DISPLAY" | awk '/dimensions:/{print $2}')
    [ -n "$SIZE" ] || { echo "[-] Could not autodetect screen size; set SIZE=WIDTHxHEIGHT" >&2; exit 1; }
fi

echo "[-] Grabbing $GRAB at $SIZE @ ${FPS}fps -> $OUT   (Ctrl-C to stop)"
sleep "$PREROLL"

exec ffmpeg -hide_banner -loglevel warning \
    -f x11grab -framerate "$FPS" -video_size "$SIZE" -i "$GRAB" \
    -c:v libx264 -preset ultrafast -qp 0 -pix_fmt yuv420p \
    "$OUT"
