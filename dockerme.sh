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

rm -f /tmp/.docker.xauth*
XAUTH=/tmp/.docker.xauth
XSOCK=/tmp/.X11-unix
DRI=/dev/dri/card0
touch ${XAUTH}
xauth nlist :0 | sed -e 's/^..../ffff/' | xauth -f ${XAUTH} nmerge -

ROOT="-u user"
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
            
exec docker run --rm $ROOT $NETWORK -it                      \
        --entrypoint /bin/bash                               \
        -v "$PWD":/workdir                                   \
        -v "$XDG_RUNTIME_DIR"/pulse:"$XDG_RUNTIME_DIR"/pulse \
        -e DISPLAY                                           \
	-e XAUTHORITY=${XAUTH}                               \
	-e PULSE_SERVER=unix:"$XDG_RUNTIME_DIR"/pulse/native \
	-v /tmp/.X11-unix:/tmp/.X11-unix                     \
	-v /dev/shm:/dev/shm                                 \
        -v $DRI:$DRI                                         \
        -v ${XSOCK}:${XSOCK}                                 \
        -v ${XAUTH}:${XAUTH}                                 \
        -w /workdir                                          \
        ${PORT}                                              \
        fasting3
