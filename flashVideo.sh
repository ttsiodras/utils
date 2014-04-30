#!/bin/bash
#
# Fetch flash video currently shown in my browser.
#
if [ $# -ne 1 ] ; then
    echo Usage: $0 filenameToSave
    exit 1
fi
FILENAME=$1
PIDS=$(pidof plugin-container | sed 's, ,\n,g' | wc -l)
if [ $PIDS -ne 1 ] ; then
    echo There are more than one instances of plugin-container...
    ps aux | grep plugin-container
    echo -n "Which one to use? "
    read PID
else
    PID=$(pidof plugin-container)
fi
BUFFER1="/dev/shm/$FILENAME"
BUFFER2="${BUFFER1}.new"
cat /proc/$PID/fd/15 > "$BUFFER1"
while true ; do
    sleep 5
    cat /proc/$PID/fd/15 > "$BUFFER2"
    if [ $(stat -c '%s' "$BUFFER1") -lt $(stat -c '%s' "$BUFFER2") ] ; then
        mv "$BUFFER2" "$BUFFER1"
        ls -l "$BUFFER1"
    fi 
done
