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
#
# ffmpeg \
#     -extra_hw_frames 64 \
#     -hwaccel vaapi \
#     -vaapi_device /dev/dri/renderD128 \
#     -hwaccel_output_format vaapi \
#     -i "$1" \
#     -vf 'format=nv12,hwupload' \
#     -c:v hevc_vaapi \
#     -qp 28 \
#      -c:a copy "$TARGET" \
#     "$TARGET"
#
# ffmpeg \
#     -extra_hw_frames 64 \
#      -hwaccel vaapi \
#      -vaapi_device /dev/dri/renderD128 \
#      -hwaccel_output_format vaapi \
#      -i "$1" \
#      -c:v hevc_vaapi \
#      -qp 28 \
#      -c:a copy \
#      "$TARGET"
#
# ffmpeg \
#     -extra_hw_frames 64 \
#     -vaapi_device /dev/dri/renderD128 \
#      -i "$1" \
#     -vf 'format=p010,hwupload,scale_vaapi=w=3200:h=1600:format=p010' \
#     -c:v hevc_vaapi \
#     -qp 28 \
#     -c:a copy \
#     -noautoscale \
#      "$TARGET"
#
# ffmpeg \
#     -extra_hw_frames 64 \
#     -vaapi_device /dev/dri/renderD128 \
#      -i "$1" \
#     -vf 'format=nv12,hwupload,scale_vaapi=w=3200:h=1600:format=nv12' \
#     -c:v hevc_vaapi \
#     -qp 28 \
#     -c:a copy \
#     -noautoscale \
#      "$TARGET"
# 
#     -vf 'format=nv12,hwupload,scale_vaapi=w=3200:h=1600' \
#
#     -vf 'hwupload,scale_vaapi=w=3200:h=1600' \
#
# fmpeg \
#     -extra_hw_frames 64 \
#     -hwaccel vaapi \
#     -hwaccel_device /dev/dri/renderD128 \
#     -hwaccel_output_format vaapi \
#      -i "$1" \
#     -vf scale_vaapi=w=3200:h=1600 \
#     -c:v hevc_vaapi \
#     -qp 28 \
#     -c:a copy \
#     -noautoscale \
#      "$TARGET"

# Claude, you unbelievable genius
#
# -extra_hw_frames 64 - -extra_hw_frames 64 tells ffmpeg to allocate 64 extra surfaces in the VAAPI hardware frame pool
# beyond what it calculates as the minimum needed. Why it's sometimes necessary: The VAAPI frame pool is pre-allocated.
# ffmpeg estimates how many surfaces the pipeline needs, but it can undercount when you have:
#   Lookahead / B-frame buffering in the encoder
#   Multiple filters in the chain each holding references to frames simultaneously
#   Hardware decode + encode in the same pipeline (both ends are holding surfaces at once)
# If the pool runs dry mid-encode, you get errors like:
#   Cannot allocate memory
#   Failed to upload frame to VAAPI device
# It's just a buffer of extra surfaces. Each surface at 1080p NV12 is roughly 3–6 MB, so 64 extra surfaces costs you maybe
# 200–400 MB of GPU-accessible memory — usually not a concern on a modern system.
#
# -hwaccel vaapi — decode on the GPU
#
# -hwaccel_device — moved before -i (applies to input)
#
# -hwaccel_output_format vaapi — keeps decoded frames in GPU memory,
#     so you skip the format=nv12,hwupload step entirely (frames never touch the CPU between decode and encode)
#
# -i inputfile ...
#
# -vf scale_vaapi alone is sufficient since frames are already in VAAPI surface memory. Scale for Quest1.
#
# -noautoscale tells ffmpeg not to automatically insert a scale filter if the output resolution doesn't match what the encoder expects.
#    Without it, ffmpeg may silently add its own scaling step if there's any dimension mismatch (e.g., odd width/height, 
#    or alignment requirements of the encoder). That auto-inserted scale would run on the CPU, which would be counterproductive
#    in a VAAPI pipeline. It's a reasonable defensive flag to have — it ensures ffmpeg doesn't sneak in a surprise software scale
#    stage after your GPU scale. Position doesn't matter for this flag by the way — it's an output option and ffmpeg parses all output options
#    together regardless of order before the output filename.
# 
# ffmpeg \
#     -extra_hw_frames 64 \
#     -hwaccel vaapi \
#     -hwaccel_device /dev/dri/renderD128 \
#     -hwaccel_output_format vaapi \
#     -i "$1" \
#     -vf scale_vaapi=w=3200:h=1600 \
#     -c:v hevc_vaapi \
#     -qp 28 \
#     -c:a copy \
#     -noautoscale \
#     "$TARGET"
#
# For CPU decoding but GPU encoding:

ffmpeg \
    -extra_hw_frames 64 \
    -vaapi_device /dev/dri/renderD128 \
    -i "$1" \
    -vf 'format=nv12,hwupload,scale_vaapi=w=iw:h=ih:format=nv12' \
    -c:v hevc_vaapi \
    -qp 28 \
    -c:a aac \
    -noautoscale \
    "$TARGET"

# ffmpeg \
#     -extra_hw_frames 64 \
#     -hwaccel vaapi \
#     -hwaccel_device /dev/dri/renderD128 \
#     -hwaccel_output_format vaapi \
#     -i "$1" \
#     -c:v hevc_vaapi \
#     -qp 28 \
#     -c:a copy \
#     -noautoscale \
#     "$TARGET"

exit $?
