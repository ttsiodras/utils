#!/bin/sh
#
# Extract proper VOB subtitles. Identify them first:
#
# mpegdemux -c -k -s all -p all  < VTS_01_1.VOB
# 
# and identify lines like:
# 0000400e: sid=bd[80] MPEG2 pts=25854[0.2873]
# 0008b80e: sid=bd[21] MPEG2 pts=605454[6.7273]
# 014ad80e: sid=bd[20] MPEG2 pts=5159454[57.3273]
# 014cf80e: sid=bd[24] MPEG2 pts=5177454[57.5273]
#                   |
# ------------------'
#
# Then modify the 0x20 below to what you need.
# Oh, and you also need the .IFO - otherwise the colors are wrong.
mkdir -p subs
cd subs
BASE=$(basename "../$1" .vob) || exit 1
cat "../$1" | tcextract -x ps1 -t vob -a 0x20 > subtitle.ps
subtitle2vobsub -p subtitle.ps -i ../VTS_01_0.IFO -o "$BASE"
rm subtitle.ps
ls -l
