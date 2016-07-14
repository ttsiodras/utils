#!/bin/bash
#
# Extract the audio contents of any media file to a LAME-encoded .mp3
#
if [ $# -ne 2 ] ; then
	echo Usage: "$0" file output.mp3
	exit 1
fi
mplayer -ao pcm:file=/dev/shm/test.$$.wav -vo null -vc dummy -benchmark "$1"
cd /dev/shm || exit 1
lame test.$$.wav
rm test.$$.wav
cd - || exit 1
mv /dev/shm/test.$$.mp3 "$2"
