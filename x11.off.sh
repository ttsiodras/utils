#!/bin/bash
( sleep 1 ; keyboard.leds.off ) &
i3lock -c 000000
keyboard.leds.on
# cd /sys/class/backlight/amdgpu_bl1
# MAXBRIGHTNESS=$(cat max_brightness)
# echo 10 | sudo tee  brightness 
# read ANS 
# echo $MAXBRIGHTNESS | sudo tee  brightness 
# echo 3 | sudo tee /sys/class/leds/asus::kbd_backlight/brightness

# echo 0 | sudo tee /sys/class/backlight/intel_backlight/brightness
# # echo 0 | sudo tee "/sys/class/leds/smc::kbd_backlight/brightness"
# read -r ANS
# cat /sys/class/backlight/intel_backlight/max_brightness | \
#    sudo tee /sys/class/backlight/intel_backlight/brightness
# # echo 100 | sudo tee "/sys/class/leds/smc::kbd_backlight/brightness"
