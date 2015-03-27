#!/bin/bash
#
# Must cleanup after my containers/images cruft
#
docker rm $(docker ps -a -q)
docker rmi $(docker images | grep ^.none | awk '{print $3}')
