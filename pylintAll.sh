#!/bin/bash
for i in "$@" ; do
    echo -n "$(printf "%30s :  " "$i")" 
    pylint "$i" | grep rated 
done
