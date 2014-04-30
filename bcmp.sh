#!/bin/bash
#
# Compare two files in binary, and show all offsets and bytes where they differ
cmp -l "$@" | gawk '{printf "%08X %02X %02X\n", $1, strtonum(0$2), strtonum(0$3)}'
