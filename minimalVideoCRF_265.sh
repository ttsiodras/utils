#!/bin/bash
ffmpeg -i "$1" -c:v libx265 -crf 25 -preset fast -c:a aac -b:a 128k /dev/shm/output265.mp4
