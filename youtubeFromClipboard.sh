#!/bin/bash
LAST_URL=""
SITES='youtube.com|framatube|vimeo.com|youtu.be|192.168.1.22|atomicpi'

while true
do
    URL="$(timeout 2 xclip -o 2>/dev/null)" 
    if [ "$LAST_URL" == "$URL" ] ; then
        sleep 1 
        if [ -f /tmp/stopyou ] ; then
            break
        else
            continue
        fi
    fi
    echo "$URL" | grep -E "$SITES" >/dev/null && {
        LAST_URL="$URL"
        echo '[-] Got URL: '"$URL"
        echo '[-] Cleaning clipboard...'
        while true
        do
            echo "" | timeout 2 xclip 
            TST="$(timeout 2 xclip -o 2>/dev/null)"
            [ "${TST}" == "" ] && break
            sleep 0.1
        done
        echo '[-] Clipboard cleaned, playing video...'
        echo "$URL"  > /dev/shm/last_video
        WORKSPACE=$(i3-msg -t  get_workspaces |  jq 'map([.num, .visible])' | grep -B1 true | head -1 | sed 's/[, ]*//g')
        i3-msg 'workspace 9; exec xterm -e mpv -fs "'"$URL"'"'
        sleep 1
        i3-msg "workspace ${WORKSPACE}"
        continue
    }
    echo "$URL" | grep "^zathura: http" >/dev/null && {
        LAST_URL="$URL"
        URL="$(echo "$URL" | sed 's,^zathura: ,,')"
        if pgrep firefox > /dev/null ; then
            notify-send "Placed URL in clipboard, go to firefox!"
            echo "$URL" | xclip
        else
            sudo su - browser -c "/home/browser/bin.local/firefox.sh \"$URL\"" &
        fi
        sleep 1 
        if [ -f /tmp/stopyou ] ; then
            break
        else
            continue
        fi
    }
    sleep 1 
    [ -f /tmp/stopyou ] && break
done
