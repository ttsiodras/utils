#!/bin/bash
while [ $# -ne 0 ] ; do
    BR=$(ffprobe "$1" |& grep -B1 Audio: | grep Duration | sed 's,^.*bitrate: \(.*\) kb/s.*,\1,' | tr -d '\012')
    [ -n "$BR" ] && echo "$BR @@@ $1"
    shift
done
