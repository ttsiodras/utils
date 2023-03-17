#!/usr/bin/env python3
import os
import sys


def computeRate(input_video):
    keys = [
        'ID_VIDEO_WIDTH',
        'ID_VIDEO_HEIGHT',
        'ID_LENGTH',
        'ID_AUDIO_BITRATE',
        'ID_VIDEO_FPS']
    values = {}
    for line in os.popen(
            "mplayer -identify -frames 0 -vo null \"%s\" 2>/dev/null" %
            input_video).readlines():
        for key in keys:
            if line.startswith(key):
                try:
                    values[key] = float(line.strip().split('=')[1])
                except:
                    panic("Failed to parse %s..." % line.strip())
                break
    for key in keys:
        if key not in values.keys():
            if key == "ID_AUDIO_BITRATE":
                continue
            print("Failed to find %s for %s" % (key, input_video))
            return -1
    file_size = os.stat(input_video).st_size
    w, h, t, aud_bps, fps = [values.get(k,0.0) for k in keys]
    if w*h*fps*t == 0.0:
        print("N/A for %s  %s" % (input_video, str((w,h,fps,t))))
        return -1
    return (8*file_size - t*aud_bps)/(w*h*fps*t)

m = max(len(x) for x in sys.argv[1:])
for f in sys.argv[1:]:
    print("%*s : %.3f" % (m, f, computeRate(f)))
