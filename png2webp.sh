#!/bin/bash
for i in *.png ; do
    ffmpeg -i "$i" "${i%.png}.webp" && \
        exiftool -tagsFromFile "$i" "-Description<Parameters" "-all:all>all:all" -overwrite_original "${i%.png}.webp"
done
