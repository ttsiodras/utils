#!/bin/bash
ffmpeg -i "$1" -c:v libx265 -crf 28 -preset fast -c:a aac -b:a 128k output265.mp4
