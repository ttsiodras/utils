#!/bin/bash
ffmpeg \
    -nostdin \
    -hwaccel cuda \
    -hwaccel_output_format cuda \
    -i "$1" \
    -c:v av1_nvenc \
    -preset p5 \
    -cq 39 \
    -rc-lookahead 32 \
    -spatial-aq 1 \
    -temporal-aq 1 \
    -multipass fullres \
    -highbitdepth 1 \
    -c:a copy \
    "$1".AV1.HEVC.mp4
