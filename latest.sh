#!/bin/bash
#
# UNIX power - makes latest.py obsolete.
#
DIR=${1:-.}
find "${DIR}" -xdev ! -type d -printf "%C+ %11s %p\\n" | sort -n
