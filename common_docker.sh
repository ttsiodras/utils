#!/bin/bash
# common_docker.sh - shared docker helpers for the launchers. Sourced:
#   . "$HOME/bin/common_docker.sh" || exit 1
#
# `docker system prune` is fine and stays fine: it deletes networks no running
# container uses. A launcher that needs one recreates it here, on demand, with
# exactly the definition the tier expects - and refuses to run on a network that
# exists with a different one (a silently different subnet would leave the
# tor airgap with nothing to apply to).
#
# restricted_net is deliberately not here: the boot path creates it (from the
# standalone vim repo) and cclog.sh creates/verifies it inline, so it stays
# self-contained.

_common_docker_check_net() {
    local name=$1 want_subnet=$2 want_internal=$3 got_subnet got_internal
    got_subnet=$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' "$name" 2>/dev/null)
    got_internal=$(docker network inspect -f '{{.Internal}}' "$name" 2>/dev/null)
    if [ "$got_subnet" != "$want_subnet" ] || [ "$got_internal" != "$want_internal" ]; then
        echo "common_docker_ensure_net: $name is subnet=$got_subnet internal=$got_internal," \
             "expected subnet=$want_subnet internal=$want_internal - refusing to use it" >&2
        return 1
    fi
}

common_docker_ensure_net() {
    local name=${1:?usage: common_docker_ensure_net <tor_net>} created=0
    shift
    if [ $# -ne 0 ]; then
        echo "common_docker_ensure_net: $name takes no extra arguments (got: $*)" >&2
        return 2
    fi
    docker network inspect "$name" >/dev/null 2>&1 || {
        echo "[-] creating missing docker network: $name" >&2
        created=1
    }
    case $name in
        tor_net)
            [ $created -eq 1 ] && {
                docker network create --internal --subnet 172.31.0.0/24 tor_net || return 1
            }
            _common_docker_check_net "$name" 172.31.0.0/24 true ;;
        *)
            echo "common_docker_ensure_net: unknown network '$name'" >&2
            return 2 ;;
    esac
}
