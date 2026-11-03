#!/bin/bash
ffmpeg -hide_banner -nostdin -i "$1" -af loudnorm=print_format=json -vn -f null - 2>&1 | \
    grep -E 'input_i|input_tp' 
