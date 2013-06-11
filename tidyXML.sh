#!/bin/sh
#
# Reindent and cleanup XML
#
tidy -utf8 -xml -w 255 -i -c -q -asxml "$@"
