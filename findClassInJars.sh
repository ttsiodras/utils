#!/bin/bash
#
# For those case where I need to find a class inside a collection of jars
#
if [ $# -lt 2 ] ; then
	echo Usage: $0 className jars...
	exit 1
fi
CLASSNAME="$1"
shift
unset _JAVA_OPTIONS
for JAR in $@ ; do
    jar tvf $JAR | grep "$CLASSNAME" && echo $JAR
done
