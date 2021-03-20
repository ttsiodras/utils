#!/bin/bash
#
# Record whatever PulseAudio is currently playing, into "stream.ogg"
#
IDX=$(pacmd list-sink-inputs | grep index | nth -1)
pactl load-module module-null-sink sink_name=steam
pactl move-sink-input $IDX steam
parec -d steam.monitor | oggenc -b 192 -o stream.ogg --raw -
