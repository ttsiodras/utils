#!/bin/bash
#
# Generate a very simple horizontal barchart of the time some task takes,
# as measured from 'time'. Remember to pipe stderr!
#
# Example:
# 
#    $ for i in {1..10} ; do T=$(echo $RANDOM | cut -c 1-2 | \
#        sed 's,^\(.\),\1.,') ; time sleep $T ; done |& \
#        barChartTimes.sh 
#
#     01 ===
#     02 =====
#     03 =
#     07 =
#
awk '/^real/ { print $NF; }' "$@" | \
             sed 's/m/:/;s/\..*$//;s/:/*60+/'  | \
             bc | \
             sort -n | \
             uniq -c | \
             perl -pe 's/^\s*(\d+)\s+(\d+)$/sprintf("%02d ", $2)."="x$1/e'
