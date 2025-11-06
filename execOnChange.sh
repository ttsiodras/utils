#!/bin/bash
#
# Usage:
#     execOnChange.sh "some command with params" "-iname *.md"
#
# Anything that matches the find filespec changes? Run the cmd.
# (i.e. instant make-like reacting on file changes)
#
if [ $# -ne 2 ] ; then 
    echo 'Usage: execOnChange.sh "some command with params" "-iname ..."'
    exit 1
fi
command="$1"
shift
fileSpec="$@"
sentinel=/tmp/t.$$
 
touch -t197001010000 $sentinel
while :
do
    set -f
    files=$(find . -type f -newer $sentinel -a \( $fileSpec \) )
    if [ $? != 0 ]; then
        exit 1;
    fi
    set +f
    if [ ! -z "$files" ]; then
        echo -e "\nChanged:" $files
        echo -e "Executing $command ..."
        touch $sentinel
        bash -c "$command"
    fi
    sleep 1
done
