#!/bin/bash
# common_xauth.sh - shared X-cookie setup for the container launchers.
# Sourced, not executed:   . "$HOME/bin/common_xauth.sh" || exit 1
#
# Every launcher needs the same cookie dance, and it is security-sensitive:
# the cookie must live in a private directory. A fixed, predictable path in the
# world-writable /tmp can be pre-created as a symlink by another uid, which
# would (a) write the X cookie through to a file of their choosing, or (b)
# bind-mount an arbitrary host path into the container.
#
#   common_xauth_init <name> [--readable]
#
# Sets XAUTHDIR and XAUTH and arms the EXIT trap that removes the directory.
# The cookie's mode only has to satisfy the container user - host-side
# isolation comes from the 0700 dir (and $XDG_RUNTIME_DIR, also 0700):
#   (default)   0600, owned by the invoking user. Correct for every local
#               image: they run as root or as uid 1000, which is the invoking
#               user (covert/fasting/fasting-mv/fasting-mv-tor all have
#               user:1000, and that is not going to change).
#   --readable  0644, only for launchers whose image is not present locally
#               (chromium*, fasting-mium*, kodi*), so their container uid
#               cannot be verified; it is the mode those scripts used before.
#
#   common_xauth_disarm   drop the EXIT trap, for a launcher that backgrounds
#                         the container: the bind source is resolved after the
#                         script exits, so the dir must outlive it - remove it
#                         after the container ends instead (see tory.sh).
common_xauth_init() {
    local name=${1:?common_xauth_init: name required}
    local mode=600
    if [ "${2:-}" = --readable ]; then
        mode=644
    fi
    XAUTHDIR=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/${name}-xauth.XXXXXXXX") || exit 1
    trap 'rm -rf "$XAUTHDIR"' EXIT
    XAUTH=$XAUTHDIR/.docker.xauth
    : > "$XAUTH"   # xauth nmerge needs the file to exist; the dir is 0700, so no symlink risk
    xauth nlist :0 | sed -e 's/^..../ffff/' | xauth -f "$XAUTH" nmerge -
    chmod "$mode" "$XAUTH"
}

common_xauth_disarm() {
    trap - EXIT
}

# Pulse socket directory, with the fallback the fasting scripts used: some login
# paths leave $XDG_RUNTIME_DIR unset.
PULSEDIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# common_docker_args <array-name> [--pulse session|bridge|none] [--no-dri] [--no-shm]
#
# Fills <array-name> with the plumbing every launcher shares, so a script only
# lists what is specific to its container. Defaults: session pulse, /dev/dri/card0
# and /dev/shm mounted.
#   session - the session's own pulse socket (microphone included)
#   bridge  - the playback-only audiobridge, no capture
#   none    - no audio at all
common_docker_args() {
    local -n _cda_out=$1
    shift
    local pulse=session dri=1 shm=1
    while [ $# -gt 0 ]; do
        case $1 in
            --pulse)  pulse=${2:?--pulse needs session, bridge or none}; shift 2 ;;
            --no-dri) dri=0; shift ;;
            --no-shm) shm=0; shift ;;
            *) echo "common_docker_args: unknown option: $1" >&2; return 2 ;;
        esac
    done
    _cda_out=( -e DISPLAY -e XAUTHORITY="$XAUTH"
               -v "${XAUTH}:${XAUTH}" -v /tmp/.X11-unix:/tmp/.X11-unix )
    if [ "$dri" = 1 ]; then _cda_out+=( -v /dev/dri/card0:/dev/dri/card0 ); fi
    if [ "$shm" = 1 ]; then _cda_out+=( -v /dev/shm:/dev/shm ); fi
    case $pulse in
        session) _cda_out+=( -v "${PULSEDIR}/pulse:${PULSEDIR}/pulse"
                             -e PULSE_SERVER=unix:"${PULSEDIR}/pulse/native" ) ;;
        bridge)  _cda_out+=( -v /run/audiobridge:/run/audiobridge
                             -e PULSE_SERVER=unix:/run/audiobridge/native ) ;;
        none) ;;
    esac
}
