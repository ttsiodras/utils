#!/bin/bash
# Useful in bash loops for image processing
magick "$1" -quality 80 -define webp:method=6 "$1".webp
