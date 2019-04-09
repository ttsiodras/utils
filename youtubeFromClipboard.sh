#!/bin/bash
LAST_URL=""
while true
do
    URL="$(timeout 2 xclip -o 2>/dev/null | grep ^htt | egrep 'youtube.com|vimeo.com|youtu.be|192.168.8.150' )" 
    [ ! -z "$URL" ] && [ "$LAST_URL" != "$URL" ] && {
        LAST_URL="$URL"
        echo '[-] Got URL, cleaning clipboard...'
        while true
        do
            echo "" | timeout 2 xclip 
            TST="$(timeout 2 xclip -o 2>/dev/null)"
            [ "${TST}" == "" ] && break
            sleep 0.1
        done
        echo '[-] Clipboard cleaned, playing video...'
        mpv -fs "$URL" 
    } 
    sleep 1 
    [ -f /tmp/stopyou ] && break
done
