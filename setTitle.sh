#!/bin/sh
# 
# Quickly set XTerm title. Pass any arg you want (quoted, if needed)
#
echo -ne "\033]0;$1\007"
