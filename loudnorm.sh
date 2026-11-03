#!/usr/bin/env bash

# Usage: ./loudnorm.sh input.mp4 [target_LUFS]
# Two-pass loudnorm, video copied untouched, output saved to /dev/shm/
#
# What?! What is LUFS?
#
# It stands for Loudness Units vs Full Scale
#
# It’s a measure of perceived loudness averaged over the whole clip, weighted
# to match how human ears hear, with mid frequencies counting more than deep
# bass or very high treble.  It’s different from peak level. Peaks (dBTP) tell
# you how close the loudest instant gets to clipping. LUFS tells you how loud
# the thing sounds overall.
# 
# e.g. original clip (UP video, best 10 min of animation ever):
#
# $ loudnorm_check.sh UP.mp4
#        "input_i" : "-28.54",
#        "input_tp" : "-2.50",
#
# $ loudnorm.sh UP.mp4
# ...
# $ loudnorm_check.sh /dev/shm/UP.mp4
#        "input_i" : "-13.90",
#        "input_tp" : "-1.21",
#
# The video went from -28.5 to -13.9 LUFS, and that's a dramatic change;
# the original was very quiet, and the script lifted it by about 14.6 dB,
# which is roughly 5x in amplitude.
#
# The original’s peaks were only 26 dB above its average loudness (-2.5 dBTP
# against -28.54 LUFS). A plain +14.6 dB gain would have pushed the peaks
# to about +12 dBTP, which is hard clipping. Since that can’t be done cleanly,
# loudnorm falls back to dynamic mode. In that mode it compresses and limits,
# so quiet parts come up a lot and loud peaks are held down.
#
# LUFS in one sentence: Higher (closer to 0) means louder. -14 is louder
# than -28, and each 1 LU is about 1 dB.  Typical targets: -23 for broadcast TV,
# -14 for most streaming and music, -16 for podcasts. The original at
# -28.5 was well below all of them, which is why it sounded so quiet.
#
# the I=-14 default in the script means “make the overall loudness
# about -14 LUFS”. The “I” stands for integrated, meaning averaged over the entire file.

set -euo pipefail

[ $# -ge 1 ] || { echo "Usage: $0 input_video [target_LUFS, default -14]"; exit 1; }
in="$1"
target="${2:--14}"

base="$(basename "$in")"
ext="${base##*.}"
out="/dev/shm/${base%.*}_loud.${ext}"

echo "Pass 1: measuring loudness..."
json="$(ffmpeg -hide_banner -nostdin -i "$in" \
  -af "loudnorm=I=${target}:TP=-1.5:LRA=11:print_format=json" \
  -vn -f null - 2>&1)"

get() { echo "$json" | grep "\"$1\"" | sed -E 's/.*: "([^"]+)".*/\1/'; }

mi="$(get input_i)"
mtp="$(get input_tp)"
mlra="$(get input_lra)"
mthr="$(get input_thresh)"
off="$(get target_offset)"

echo "Measured: I=$mi TP=$mtp LRA=$mlra thresh=$mthr offset=$off"
echo "Pass 2: encoding to $out ..."

ffmpeg -hide_banner -nostdin -y -i "$in" \
  -map 0:v -map 0:a:0 \
  -af "loudnorm=I=${target}:TP=-1.5:LRA=11:measured_I=${mi}:measured_TP=${mtp}:measured_LRA=${mlra}:measured_thresh=${mthr}:offset=${off}:linear=true" \
  -c:v copy -c:a aac -b:a 256k \
  "$out"

echo "Done: $out"
