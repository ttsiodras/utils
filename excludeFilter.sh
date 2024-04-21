#!/bin/bash
#
# Pipe any kind of output to this, and you will be able
# to exclude outputs interactively, filtering until you
# are left with nothing.
#
# e.g. 
#
#   latest.py | filterExclude.sh
#
# ...will allow you to see the files you've created in 
# the last few days/weeks, and filter out until you find
# that big one you somehow inflicted on your filesystem
# and forgot about.

DATA=/dev/shm/data.$$
function finish {
    rm -f $DATA
}
trap finish EXIT
# Read all stdin into a temp file that will be cleaned on exit
cat > $DATA

# And now keep reading from ACTUAL stdin (not the piped input)
# and remove lines if they match the input.
(
GR=""
tail -40 "$DATA"
echo -n Exclude this or Ctrl-D ... 
while read -r ANS ; do
    if [ ! -z "$ANS" ] ; then
        [ -z "$GR" ] && GR="$ANS" || GR="$GR|$ANS"
        grep -E -v "$GR" "$DATA" | tail -40
        echo "-v $GR $DATA" > /dev/shm/filter
    else
        grep -E -v "$GR" "$DATA" | tail -40
    fi
done ) <&1
