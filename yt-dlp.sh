#!/bin/bash
#
# This allows me to launch the yt-dlp container (see
# Dockerfiles/Dockerfile.yt-dlp) with the current folder mapper under /workdir.
# Much more secure than running all this galaxy of code without a sandbox.

usage() {
    echo -e "Usage: $0 [-h] [-r] [-n] [-p 9999]"
    echo -e "Where:"
    echo -e "\t-h\t\tshow this help"
    echo -e "\t-r\t\truns container with root user"
    exit 1
}

ROOT="-u 1000"
PORT=""

while getopts "hnrp:" o ; do
    case "${o}" in 
        h)
            usage
            ;;
        r)
            ROOT="-u root"
            ;;
        *)
            usage
            ;;
    esac
done
            
exec docker run --rm $ROOT -it -v "$PWD":/workdir -w /workdir yt-dlp "$@"
