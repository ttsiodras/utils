#!/bin/bash

# For playing back Youtube streams with just music
# (no need to waste CPU / trigger fans)
#
# If no parameter is passed, falls back on the
# "Beautiful Piano Music 24/7" stream.

URL=${1:-https://www.youtube.com/watch?v=y7e-GC6oGhg}
mpv --no-video --profile=pseudo-gui "${URL}"
