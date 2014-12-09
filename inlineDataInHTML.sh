#!/bin/bash
#
# Generate HTML-embeddable representations of file data.
# (data_URI scheme)
#
if [ $# -ne 1 ] ; then
    echo Usage: $0 file
    exit 1
fi
echo -n "data:" ; mimetype -b "$1" | tr -d '\12' ; echo -n ';base64,' ; cat "$1" | base64 -w 0
