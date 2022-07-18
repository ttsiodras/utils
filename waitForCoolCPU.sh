#!/bin/bash
THRESHOLD=${1:-65}
while true ; do
    TEMP=$(sensors | grep ^Core | nth 2 | sed 's,[^0-9\.],,g' | sort -n | tail -1 | sed 's,\..*$,,')
    [ "${TEMP}" -lt $THRESHOLD ] && break
    echo -n "${TEMP}C... "
    sleep 1
done
echo "${TEMP}C. Go!"
