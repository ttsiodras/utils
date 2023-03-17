#!/usr/bin/env python3
import os
import re
import sys

options = "-v quiet -print_format json -show_format -show_streams"

for fname in sys.argv[1:]:
    quoted_single_quotes = "'\"'\"'"
    fname = fname.replace("'", quoted_single_quotes)

    if 0 != os.system(f"ffprobe {options} '{fname}' -o /dev/shm/data"):
        sys.exit(1)

    print("File:", sys.argv[1])
    jq = "jq '.streams[].duration' /dev/shm/data"
    duration_in_sec = max(
        float(eval(x))
        for x in os.popen(jq).readlines())
    print("Duration:", duration_in_sec)

    jq = "jq '.streams[] | select(.channels > 0) | .bit_rate' /dev/shm/data"
    audio_bitrates = [
        float(eval(x))
        for x in os.popen(jq).readlines()]
    print("Audio bitrates:", audio_bitrates)

    for f in ['width', 'height', 'avg_frame_rate']:
        jq = f"jq '.streams[].{f}' /dev/shm/data"
        for x in os.popen(jq).readlines():
            try:
                globals()[f] = max(globals().get(x, 0), float(eval(x)))
            except:
                try:
                    globals()[f] = max(globals().get(x, 0), float(eval(eval(x))))
                except:
                    pass
            else:
                break
    print("Height:", height)
    print("Width:", width)
    print("Avg frame rate:", avg_frame_rate)

    file_size = os.stat(sys.argv[1]).st_size
    audio_data_size = duration_in_sec*sum(audio_bitrates)/8
    video_data_size_per_sec = (file_size - audio_data_size)/duration_in_sec
    video_data_size_per_frame = video_data_size_per_sec / avg_frame_rate
    print("Video rate in bits/pixel: %.2f" % (8*video_data_size_per_frame / (width * height)))

    print("Ideal h264 bitrate: %.2f\n" % (width*height*avg_frame_rate*0.05))
os.unlink("/dev/shm/data")
