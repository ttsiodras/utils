#!/bin/bash
#
# Much better than plain old "du -s -m/-k" - this actually
# adds file sizes, so it's much more filesystem agnostic.
#
if [ $# -lt 1 ] ; then
        echo Usage: $0 dir1 dir2 ...
        exit 1
fi
while [ $# -ne 0 ] ; do
        [ ! -d "$1" ] && { shift ; continue ; }
        echo "$1" | awk '{printf("%40s:", $0);}'
        find "$1"/ -type f -printf '%s\n' | awk '{a+=$1;}END{printf("%12d KB (%9d MB)\n", int(a/1024.0), a/1048576);}'
        shift
done
