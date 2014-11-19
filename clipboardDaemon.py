#!/usr/bin/env python
'''
I've had it with syncing X and the clipboard.
I was using autocutsel, but sometimes it doesn't work -
replaced it with this quick hack. 

Seems to work perfectly so far... Needed 'awk 1' to add
a newline when it was missing.
'''
import os
import time
from collections import namedtuple

make_state = namedtuple("State", ["xwin", "clipboard"])
getX = "xclip -selection primary -o 2>/dev/null"
getClip = "xclip -selection clipboard -o 2>/dev/null"
setX = getX.replace("-o", "-i")
setClip = getClip.replace("-o", "-i")
getState = lambda: make_state(os.popen(getX).read(), os.popen(getClip).read())
state = getState()
while True:
    newState = getState()
    if newState.xwin != state.xwin:
        print "Syncing X to clipboard"
        os.system(getX + "|awk 1|" + setClip)
        state = getState()
    elif newState.clipboard != state.clipboard:
        print "Syncing clipboard to X"
        os.system(getClip + "|awk 1|" + setX)
        state = getState()
    time.sleep(0.25)
