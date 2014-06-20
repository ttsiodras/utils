#!/bin/bash
#
# I run pylint a lot - this eases the pain
#
FILES=${@:-$(echo *.py)}
for i in $FILES ; do
    echo -n "$(printf "%30s :  " "$i")" 
    pylint "$i" | grep rated 
done
