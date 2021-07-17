#!/bin/bash
ps aux | grep 'xscreen[s]aver' > /dev/null || {
    xscreensaver &
}
xscreensaver-command -lock
