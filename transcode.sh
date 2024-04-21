#!/bin/bash
# Hardware-based (VA-API) transcoding.
# Even on my AtomicPI, this is much faster than SW-only...
if [ $# -ne 2 ] ; then 
    echo Usage: $0 input_file output.mp4
    exit 1
fi

# If you need HW rescaling add this:
# -vf scale_vaapi=w=3840:h=1920 \

# If you need to control BW precisely, use this:
# -b:v 2M -maxrate 2M
ffmpeg  \
    -hwaccel vaapi \
    -vaapi_device /dev/dri/renderD128 \
    -hwaccel_output_format vaapi \
    -i "$1" \
    -c:v h264_vaapi \
    -crf 23 \
    "$2"
