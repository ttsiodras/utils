#!/bin/bash
ffmpeg \
    -nostdin \
    -hwaccel cuda \
    -hwaccel_output_format cuda \
    -i "$1" \
    -c:v hevc_nvenc \
    -cq 31 \
    -preset p4 \
    -rc-lookahead 20 \
    -spatial_aq 1 \
    -c:a aac \
    -b:a 128k \
    "$1".HEVC.mp4
