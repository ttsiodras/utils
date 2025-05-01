#!/bin/bash
[ -d /proc/"$1" ] || {
    echo "No such process pid: $1"
    exit 1
}
gdb -q -p "$1" -batch \
    -ex "thread apply all bt" \
    -ex "detach" \
    -ex "quit"
