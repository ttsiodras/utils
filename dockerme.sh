#!/bin/bash
#
# This allows me to launch a container with the current folder
# mapper under /workdir. By default it's quite secure, allowing
# access to pulse and X11, but nothing else (no network).
# 
# Launch with -n to have network - and with -r to be root.

usage() {
    echo -e "Usage: $0 [-h] [-r] [-n] [-p 9999]"
    echo -e "Where:"
    echo -e "\t-h\t\tshow this help"
    echo -e "\t-p port\t\tExpose port"
    echo -e "\t-r\t\truns container with root user"
    echo -e "\t-n\t\truns container with network enabled"
    exit 1
}

# Hardening (audit F-34): a private 0700 xauth dir per run, not the fixed
# /tmp/.docker.xauth - another uid can pre-create that name as a symlink and
# make us write the X cookie through to a file of their choosing.
. "$HOME/bin/common_xauth.sh" || exit 1
common_xauth_init dockerme

ROOT="-u 1000"
NETWORK="--network=none"
PORT=""

while getopts "hnrp:" o ; do
    case "${o}" in 
        h)
            usage
            ;;
        n)
            NETWORK=""
            ;;
        r)
            ROOT="-u root"
            ;;
        p)
            PORT="-p ${OPTARG}"
            ;;
        *)
            usage
            ;;
    esac
done
            
common_docker_args DARGS
docker run "${DARGS[@]}" --rm $ROOT $NETWORK -it                      \
        --entrypoint /bin/bash                               \
        -v "$PWD":/workdir                                   \
        -w /workdir                                          \
        ${PORT}                                              \
        fasting

