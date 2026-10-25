#!/bin/bash
# Useful in bash loops with audio processing
ffprobe -i "$1" -show_entries format=duration -v quiet -of csv="p=0"
