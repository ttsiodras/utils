# How to create nice looking, losslessly compressed screen captures.
rm /tmp/out.mpg ; sleep 2 ; ffmpeg -f x11grab -s 1280x1024 -r 25 -i :0.0 -sameq /tmp/out.mpg
ffmpeg -i out.mpg -vcodec libx264 -vpre lossless_fast -crf 22 -threads 6 out.flv
mplayer -osdlevel 0 -fs out.flv
