#!/bin/bash
#
# This allows me to launch the yt-dlp container (see
# Dockerfiles/Dockerfile.yt-dlp.binary) with the current folder mapped under /workdir.
# Much more secure than running all this galaxy of code without a sandbox.
# The container writes as uid 1000, so loosen this folder for the duration of
# the run and put the original mode (sticky bits included) back on the way out.
ORIG_MODE=$(stat -c '%a' .) || exit 1
trap 'chmod "${ORIG_MODE}" .' EXIT
chmod 777 .
docker run --rm -u 1000 -it -v "$PWD":/workdir -w /workdir yt-dlp "$@"
