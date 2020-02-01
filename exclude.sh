#!/bin/bash
#
# This is used in combination with my latest.py script:
#
#    cd /some/path
#    latest.py > /var/tmp/listOfFilesOrderedByTime
#    exclude.sh /var/tmp/listOfFilesOrderedByTime
#
# ...and then you enter regexps to exclude, until you've 
# reviewed all you need.
#
GR=""
tail -40 "$1"
echo -n Exclude this or Ctrl-D ... 
while read ANS ; do
    [ -z "$GR" ] && GR="$ANS" || GR="$GR|$ANS"
    egrep -v "$GR" "$1" | tail -40
    echo "-v $GR $1" > /dev/shm/filter
done
