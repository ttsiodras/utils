#!/bin/bash
echo -n "Max setting: "
MAXBRIGHTNESS=$(cat /sys/class/backlight/*/max_brightness)
echo $MAXBRIGHTNESS
VAL=${1:-$MAXBRIGHTNESS}
# VAL=$(($VAL / 2))
echo $VAL | sudo tee /sys/class/backlight/*/brightness
