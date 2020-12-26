#!/bin/bash
#
# Show the currently executing command line inside a bash shell.
#
# Relevant blog post:
#    https://www.thanassis.space/bashheimer.html
#
if [ $# -ne 1 ] ; then
    echo Usage: $0 BASH_PID
    exit 1
fi
if [ ! -d /proc/$1 ] ; then
    echo There is no such PID
    exit 1
fi
STATNAME=$(stat --format='%N' /proc/$1/exe)
if [[ $STATNAME != */bin/bash* ]] ; then
    echo This is not a bash PID
    exit 1
fi
gdb --pid $1 /proc/$1/exe >/dev/null 2>&1 <<OEF
call (int) write_history("/tmp/bash_history_recover")
detach
q
OEF
tail -1 /tmp/bash_history_recover 2>/dev/null
rm -f /tmp/bash_history_recover
