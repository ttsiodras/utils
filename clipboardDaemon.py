#!/usr/bin/env python3
'''
I've had it with syncing X and the clipboard.
I was using autocutsel, but sometimes it doesn't work -
replaced it with this quick hack.
'''
import os
import time
from collections import namedtuple


make_state = namedtuple("State", ["xwin", "clipboard"])
# On occasion, xclip blocks for ever - apparently some race
# condition in XWindows. GNU timeout to the rescue...
xclipCmd = "timeout 2 xclip -selection %s -o 2>/dev/null"
getX = xclipCmd % "primary"
getClip = xclipCmd % "clipboard"
# xclip does not (always) close STDOUT...
setX = getX.replace("-o", "-i >/dev/null")
setClip = getClip.replace("-o", "-i >/dev/null")
getState = lambda: make_state(
    os.popen(getX).read(),
    os.popen(getClip).read())
state = getState()
while True:
    debug = os.path.exists("/tmp/wtf")
    newState = getState()
    if debug:
        print("newState:", newState)
    if newState.xwin != state.xwin and newState.xwin != '':
        print(newState)
        print("Syncing X to clipboard")
        # The perl below strips the last newline
        os.system(
            getX + r"|perl -i -p0777we's/\n\z//'|" + setClip)
        state = getState()
    elif newState.clipboard != state.clipboard and newState.clipboard != '':
        print(newState)
        print("Syncing clipboard to X")
        # The perl below strips the last newline
        os.system(
            getClip + r"|perl -i -p0777we's/\n\z//'|" + setX)
        state = getState()
    time.sleep(0.25)
