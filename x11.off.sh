echo 0 | sudo tee /sys/class/backlight/intel_backlight/brightness
# echo 0 | sudo tee "/sys/class/leds/smc::kbd_backlight/brightness"
read -r ANS
cat /sys/class/backlight/intel_backlight/max_brightness | \
   sudo tee /sys/class/backlight/intel_backlight/brightness
# echo 100 | sudo tee "/sys/class/leds/smc::kbd_backlight/brightness"
