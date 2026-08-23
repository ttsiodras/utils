#!/bin/bash
for i in "$@" ; do
        getfattr -n user.mergerfs.allpaths --only-values "$i" | cut -d\" -f 2 | tr '\0' '\n'
done
