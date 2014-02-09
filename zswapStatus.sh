#!/bin/bash

# Show statistics about zswap

[ $(id -u) -ne 0 ] && { exec sudo $0 ; }
cd /sys/kernel/debug/zswap || exit 1
for i in * ; do printf '%25s: %s\n' $i $(cat "$i") ; done
