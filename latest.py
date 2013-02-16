#!/usr/bin/env python
import os
import sys
import time
import itertools
from stat import ST_MTIME, ST_CTIME, ST_ATIME, ST_SIZE, ST_MODE, S_ISDIR

timemode = ST_MTIME
if len(sys.argv) > 1:
    try:
        timemode = {
            "-m": ST_MTIME,
            "--mtime": ST_MTIME,
            "-a": ST_ATIME,
            "--atime": ST_ATIME,
            "-c": ST_CTIME,
            "--ctime": ST_CTIME
        }[sys.argv[1].lower()]
    except:
        timemode = ST_MTIME

target = "."
if len(sys.argv) > 1 and not sys.argv[-1].startswith("-"):
    target = sys.argv[-1]
target = os.path.abspath(target)

maxSize = 0
completeList = {}
for p, dirlist, filelist in os.walk(target):
    for f in itertools.chain(filelist, dirlist):
        fullpath = p + os.sep + f
        try:
            statdata = os.lstat(fullpath)
            timestamp = statdata[timemode]
            if S_ISDIR(statdata[ST_MODE]):
                completeList.setdefault(
                    timestamp, []).append((fullpath, -1))
            else:
                completeList.setdefault(
                    timestamp, []).append((fullpath, statdata[ST_SIZE]))
                maxSize = max(maxSize, statdata[ST_SIZE])
        except:
            pass

span = len(str(maxSize))
empty = span*" "
for k, l in sorted(completeList.items()):
    for v in l:
        if v[1] == -1:
            pass  # print "%s %s %s/" % (time.ctime(k), empty, v[0])
        else:
            print "%s %*d %s" % (time.ctime(k), span, v[1], v[0])
