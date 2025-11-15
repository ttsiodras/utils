#!/bin/bash
#
# An excellent way to get a quick look at the state of a running system
dstat -clnv --fs --vm "$@"
