import vapoursynth as vs
import vsrife
from vssource import BestSource

# Gets the VapourSynth processing engine instance. Everything runs through this object.
core = vs.core

# Opens the video file. BestSource is a high-quality decoder that indexes the file first
# (that's the 0%→100% progress you saw) to guarantee accurate seeking and frame-exact decoding.
#  The result is a clip object — think of it as a lazy frame pipeline, nothing is actually decoded yet.
clip = BestSource.source("input_3GS.mp4")

# Converts the clip from YUV (how video is stored) to RGB float32 (RGBS).
# vsrife requires RGB input. matrix_in_s="709" tells it the source uses
# BT.709 color math (standard for HD video) so the YUV→RGB conversion is correct.
clip = core.resize.Bicubic(clip, format=vs.RGBS, matrix_in_s="709")

# The actual interpolation. factor_num=2 doubles the frame rate (25→50fps...
# actually 60 would need fps_num=60, fps_den=1). Model 4.25 is the RIFE neural
# network version. sc=False disables scene change detection since we couldn't
# install the misc plugin.
clip = vsrife.rife(clip, factor_num=2, model="4.25", sc=False)

# One thing to note: factor_num=2 gives you 50fps not 60fps since your source
# is 25fps. If you actually wanted 60fps you'd need:
# clip = vsrife.rife(clip, fps_num=60, fps_den=1, model="4.25", sc=False)

# Converts back from RGB to YUV for output. YUV420P10 is 10-bit, better quality
# than the original 8-bit source — worth keeping since we're re-encoding anyway.
# matrix_s="709" applies the same BT.709 math in reverse.
clip = core.resize.Bicubic(clip, format=vs.YUV420P10, matrix_s="709")

# Marks this clip as the output that vspipe will read and pipe to FFmpeg.
clip.set_output()
