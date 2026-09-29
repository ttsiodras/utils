#!/bin/bash
#
# Decode in HW via VAAPI
# But encode in SW (much better quality)
# ...at highest resolution Q1 supports
ffmpeg -nostdin -hwaccel vaapi   -i  "$1"  -vf 'scale=w=3840:h=1920'   -c:v hevc -profile:v main10  -crf 23 -tag:v hvc1   -c:a copy   "$1".Quest.mp4
