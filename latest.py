#!/usr/bin/env python
'''
This utility shows what files were recently modified, regardless
of their folder depth. It starts by default on the current folder,
but you can also specify any folder you wish in the cmd line.

It will then display all files found under any depth, sorted by
their modification time (oldest to earliest). You can also sort
by accesstime (-a) or ctime (-c).

Think of it as a recursive "ls -ltra" - I use it to see what files
have recently changed, regardless of folder depth.
'''

import os
import sys
import time
import getopt
import itertools
from stat import ST_MTIME, ST_CTIME, ST_ATIME, ST_SIZE, ST_MODE, S_ISDIR


def usage():
    print '''\
Usage: {mainApp} <options> <folderToScan>

where folderToScan is . by default, and options can be:

    -h, --help      show this help message
    -m, --mtime     order by modification time (default)
    -a, --atime     order by access time
    -c, --ctime     order by ctime (creation time under Windows,
                    inode modification time under Unix)
'''.format(mainApp=os.path.basename(sys.argv[0]))
    sys.exit(1)


def main():
    try:
        args = sys.argv[1:]
        optlist, args = getopt.gnu_getopt(
            args, "hmac", ['help', 'mtime', 'atime', 'ctime'])
    except:
        usage()

    timemode = ST_MTIME
    for opt, unused_arg in optlist:
        if opt in ("-h", "--help"):
            usage()
        elif opt in ("-m", "--mtime"):
            timemode = ST_MTIME
        elif opt in ("-a", "--atime"):
            timemode = ST_ATIME
        elif opt in ("-c", "--ctime"):
            timemode = ST_CTIME
        else:
            usage()

    if args:
        if len(args) > 1:
            usage()
        elif not os.path.isdir(args[0]):
            print args[0], "is not a folder... Aborting..."
            sys.exit(1)
        else:
            target = args[0]
    else:
        target = "."

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
    #empty = span*" "
    for k, l in sorted(completeList.items()):
        for v in l:
            if v[1] == -1:  # Folder, I care not
                pass  # print "%s %s %s/" % (time.ctime(k), empty, v[0])
            else:
                print "%s %*d %s" % (time.ctime(k), span, v[1], v[0])

if __name__ == "__main__":
    main()
