#!/bin/bash
PREFIX=""
X265OPTS=""

# Detect NVIDIA GB10 (Grace Blackwell) — use 10 Cortex-X925 cores
if lscpu 2>/dev/null | grep -qi 'GB10'; then
    PREFIX="taskset -c 0,1,2,3,4,10,11,12,13,14"
    X265OPTS="-x265-params pools=10"
fi

$PREFIX ffmpeg \
    -nostdin \
    -i "$1" \
    -c:v libx265 -crf 26 -preset fast \
    $X265OPTS \
    -c:a libopus \
    "$1".HEVCB.mp4
