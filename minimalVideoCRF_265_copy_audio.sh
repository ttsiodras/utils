#!/bin/bash
ffmpeg \
    -i "$1" \
    -c:v libx265 -crf 26 -preset fast -c:a copy \
    "$1".HEVCB.mp4
