#!/bin/bash
ffmpeg -hwaccel vaapi -vaapi_device /dev/dri/renderD128 -hwaccel_output_format vaapi -i "$1" -c:v h264_vaapi -crf 23 -preset fast -c:a aac -b:a 128k output_264.mp4
