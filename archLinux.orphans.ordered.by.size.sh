#!/bin/bash
pacman -Qdt | while read NAME FOO ; do echo -n $NAME ; grep -A1 SIZE /var/lib/pacman/local/${NAME}*/desc | tr -d '\012' ; echo ; done | sed 's,.SIZE., ,' | sort -n -k 2
