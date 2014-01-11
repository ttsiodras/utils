#!/bin/bash
#
# UNIX power - makes latest.py obsolete.
#
DIR=${1:-.}
find "${DIR}" ! -type d -printf "%T+ %11s %p\\n" | sort -n
