vspipe interpolate.vpy - -c y4m | \
    ffmpeg -i pipe:0 \
    -i input.mp4 \
    -map 0:v \
    -map 1:a \
    -c:v hevc_nvenc \
    -cq 31 \
    -preset p4  \
    -rc-lookahead 20 \
    -spatial-aq 1 \
    -c:a copy \
    /dev/shm/2x.mp4
