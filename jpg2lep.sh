#!/bin/bash

# Use Dropbox's lepton ( https://github.com/dropbox/lepton )
# to save space in stored JPEG images without any loss.
for i in "$@" ; do
    lepton "$i" /dev/shm/lepton.$$ || { echo "$i" Failed... ; continue ; }
    DST=$(lepton /dev/shm/lepton.$$ /dev/stdout | md5sum - | nth 0)
    SRC=$(cat "$i" | md5sum - | nth 0)
    if [ "$SRC" == "$DST" ] ; then
        mv /dev/shm/lepton.$$ "$i".lep
    fi
done
