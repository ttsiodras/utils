#!/bin/sh
# 
# Quickly set XTerm title. Pass any arg you want (quoted, if needed)
#
/bin/echo -ne "\033]0;$1\007"
