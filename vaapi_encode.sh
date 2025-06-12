#!/bin/bash
BASE=$(basename "$1")
TARGET="/dev/shm/$BASE.HEVC.mp4"
#
# Sadly, -crf doesn't work for HW encoding :-(
#
# So instead of this... (which also demonstrates how to do HW rescaling)...
#
# ffmpeg -extra_hw_frames 64 -hwaccel vaapi -vaapi_device /dev/dri/renderD128 -hwaccel_output_format vaapi -i input_from_phone_recording.mp4  -vf 'format=nv12,hwupload' -vf scale_vaapi=w=1920:h=1080  -c:v hevc_vaapi -crf 28 /dev/shm/output_rescaled.mp4
#
# ...this fallback is the one that works.
# It is much, much worse quality-wise...  but still, acceptable in my tests with my phone's recordings.
ffmpeg -extra_hw_frames 64 -hwaccel vaapi -vaapi_device /dev/dri/renderD128 -hwaccel_output_format vaapi -i "$1"  -c:v hevc_vaapi -qp 28 "$TARGET"
