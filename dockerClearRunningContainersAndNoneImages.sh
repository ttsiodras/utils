#!/bin/bash
#
# Must cleanup after my containers/images cruft
#
docker ps -a -q | while read ANS ; do
    echo "Removing $ANS"
    docker rm $ANS
done
docker images | grep ^.none | awk '{print $3}' | while read ANS ; do
    echo Removing $ANS
    docker rmi $ANS
done
