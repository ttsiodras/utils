#!/bin/bash
#
# Drop color codes from an input pipe
cat | sed -e 's/\x1b\[[0-9;]*m//g'
