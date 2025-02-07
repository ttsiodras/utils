#!/bin/bash
echo 0 | sudo tee /sys/class/leds/asus::kbd_backlight/brightness
cd /sys/class/backlight/amdgpu_bl1
echo 0 | sudo tee  brightness 
read ANS 
echo 96 | sudo tee  brightness 
echo 3 | sudo tee /sys/class/leds/asus::kbd_backlight/brightness

# echo 0 | sudo tee /sys/class/backlight/intel_backlight/brightness
# # echo 0 | sudo tee "/sys/class/leds/smc::kbd_backlight/brightness"
# read -r ANS
# cat /sys/class/backlight/intel_backlight/max_brightness | \
#    sudo tee /sys/class/backlight/intel_backlight/brightness
# # echo 100 | sudo tee "/sys/class/leds/smc::kbd_backlight/brightness"
