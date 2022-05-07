#!/usr/bin/env python2
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
import collections
from stat import S_ISDIR


def usage():
    print '''\
Usage: {mainApp} <options> <folderToScan>

where folderToScan is . by default, and options can be:

    -h, --help      show this help message
    -l, --symlinks  show symlinks
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
            args, "hlmac", [
                'help', 'nosymlink', 'mtime', 'atime', 'ctime'])
    except:
        usage()

    timemode = "st_mtime"
    show_symlinks = False
    for opt, unused_arg in optlist:
        if opt in ("-h", "--help"):
            usage()
        elif opt in ("-l", "--symlinks"):
            show_symlinks = True
        elif opt in ("-m", "--mtime"):
            timemode = "st_mtime"
        elif opt in ("-a", "--atime"):
            timemode = "st_atime"
        elif opt in ("-c", "--ctime"):
            timemode = "st_ctime"
        else:
            usage()
    timemodeFunc = lambda x: getattr(x, timemode)

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

    if sys.platform.startswith("linux"):
        special_char = {
            'st_mtime': 'T',
            'st_ctime': 'C',
            'st_atime': 'A'
        }[timemode]
        cmd = 'find "{0}" ! -type d '.format(target)
        if not show_symlinks:
            cmd += ' ! -type l '
        os.system(
            cmd + '-printf "%{0}+ %11s %p\\n" | sort -n'.format(
                special_char))
    else:
        maxSize = 0
        completeList = collections.defaultdict(list)
        for p, dirlist, filelist in os.walk(target):
            for f in itertools.chain(filelist, dirlist):
                fullpath = p + os.sep + f
                try:
                    statdata = os.lstat(fullpath)
                    timestamp = timemodeFunc(statdata)
                    if not S_ISDIR(statdata.st_mode):
                        si = statdata.st_size
                        completeList[timestamp].append((fullpath, si))
                        maxSize = max(maxSize, si)
                except:
                    pass

        span = len(str(maxSize))
        for k, l in sorted(completeList.items()):
            for v in l:
                print "%s %*d %s" % (time.ctime(k), span, v[1], v[0])

if __name__ == "__main__":
    main()
