# Installation in local venv

Incrementally built in a session with Sonnet 4.6:

```
mkdir rife
cd rife
python3 -m venv .venv
.  .venv/bin/activate
python3 -m pip install vsrife
python3 -m pip install vapoursynth
pip install vssource
pip install vapoursynth-bestsource

#
# Must edit interpolate.vpy first, and put "input_3GS.mp4" as input
#

vspipe interpolate.vpy - -c y4m | \
    ffmpeg -i pipe:0 \
    -i input_3GS.mp4 \
    -map 0:v \
    -map 1:a \
    -c:v hevc_nvenc \
    -cq 31 \
    -preset p4 \
    -rc-lookahead 20 \
    -spatial_aq 1 \
    -c:a copy \
    /dev/shm/2x.mp4

cd /dev/shm/

mpv 2x.mp4
```
