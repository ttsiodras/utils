#!/bin/bash
#pdftotext "$1" /dev/stdout | grep '
for i in "$@" ; do
    pdfinfo "$i" | grep ^Pages
done | awk '{a+=$2; print a}'
