#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

if [ $# -ne 2 ] ; then
    echo "Usage: $0 <filename.jsonl> <output.md>"
    exit 1
fi
docker images | grep cclog || {
    echo "[-] Run 'make cclog' from inside ${SCRIPT_DIR}/Dockerfiles to build the cclog image."
    exit 1
}
REALPATH="$(realpath "$1")"
# Self-contained on purpose: no ~/bin helper dependency. The kill switch
# (RESTRICTED_NET in /etc/ufw/after.init) is keyed to 172.30.0.0/24, so the
# network is created with exactly that subnet - and if one already exists with
# a different subnet, refuse to run rather than let the airgap silently not apply.
docker network inspect restricted_net >/dev/null 2>&1 || {
    docker network create --driver bridge --subnet 172.30.0.0/24 \
        --opt com.docker.network.bridge.name=restricted_net restricted_net || exit 1
}
[ "$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' restricted_net)" = 172.30.0.0/24 ] || {
    echo "[x] restricted_net exists with the wrong subnet - the airgap rules would not apply" >&2
    exit 1
}
docker run --rm \
  --network restricted_net \
  -v "$REALPATH":"$REALPATH":ro \
  cclog "$REALPATH" > "$2"
