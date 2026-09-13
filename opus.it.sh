#!/bin/bash
ffmpeg -i "$1" -c:a libopus -b:a 64k "$1".64kb.opus
