#!/bin/bash
echo -n "Max setting: "
MAXBRIGHTNESS=$(cat /sys/class/backlight/intel_backlight/max_brightness)
echo $MAXBRIGHTNESS
VAL=${1:-$MAXBRIGHTNESS}
echo $VAL | sudo tee /sys/class/backlight/intel_backlight/brightness
