#!/bin/bash
for i in "$@" ; do
	getfattr -n user.mergerfs.fullpath "$i"
done
