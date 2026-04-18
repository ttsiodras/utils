#!/bin/bash
#
# This allows me to launch the yt-dlp container (see
# Dockerfiles/Dockerfile.yt-dlp) with the current folder mapper under /workdir.
# Much more secure than running all this galaxy of code without a sandbox.
chmod 777 .
exec docker run --rm -u 1000 -it -v "$PWD":/workdir -w /workdir yt-dlp "$@"
chmod 755 .
