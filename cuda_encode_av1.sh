#!/bin/bash
ffmpeg \
    -nostdin \
    -hwaccel cuda \
    -hwaccel_output_format cuda \
    -i "$1" \
    -c:v av1_nvenc \
    -preset p5 \
    -cq 35 \
    -rc-lookahead 32 \
    -spatial-aq 1 \
    -temporal-aq 1 \
    -multipass fullres \
    -highbitdepth 1 \
    -c:a aac \
    -b:a 128k \
    "$1".AV1.mp4
