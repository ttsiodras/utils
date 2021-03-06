#!/bin/bash
# Hardware-based (VA-API) transcoding.
# Even on my AtomicPI, this is much faster than SW-only...
if [ $# -ne 2 ] ; then 
    echo Usage: $0 input_file output.mp4
    exit 1
fi
ffmpeg  \
    -hwaccel vaapi \
    -vaapi_device /dev/dri/renderD128 \
    -hwaccel_output_format vaapi \
    -i "$1" \
    -c:v h264_vaapi \
    -b:v 2M \
    -maxrate 2M \
    "$2"
