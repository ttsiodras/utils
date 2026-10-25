# =============================================================================
# interpolate.vpy
#
# What this script does, in one sentence:
#   Reads input.mp4, upscales every frame 2x with Real-ESRGAN (AI upscaler),
#   then doubles the frame rate with RIFE (AI frame interpolation), and hands
#   the result to vspipe -> ffmpeg for encoding.
#
# Pipeline order:
#   decode -> convert to RGB fp16 -> Real-ESRGAN 2x upscale -> RIFE 2x fps
#          -> convert back to YUV 10-bit -> output
#
# Run it like so:
#   vspipe interpolate.vpy - -c y4m | \
#     ffmpeg -i pipe:0 \
#     -i input_3GS.mp4 \
#     -map 0:v \
#     -map 1:a \
#     -c:v hevc_nvenc \
#     -cq 31 \
#     -preset p4 \
#     -rc-lookahead 20 \
#     -spatial_aq 1 \
#     -c:a copy \
#     /dev/shm/2x.mp4
#
# NOTE: The settings below were arrived at by trial and error.
#       The RIFE line deliberately has trt=False because trt=True produced
#       corrupted (blobby noise) interpolated frames.
# =============================================================================

# --- Imports -----------------------------------------------------------------

# VapourSynth: the video processing framework this whole script runs inside.
import vapoursynth as vs

# vsrife: VapourSynth plugin wrapping RIFE, a neural network that invents the
# in-between frames (e.g. turns 25 fps into 50 fps).
import vsrife

# vsrealesrgan: VapourSynth plugin wrapping Real-ESRGAN, a neural network that
# upscales images/video and adds plausible detail.
# RealESRGANModel is the list of available pretrained models.
from vsrealesrgan import realesrgan, RealESRGANModel

# vssource: helper for opening video files. BestSource is a decoder that
# indexes the file first (the progress percentage you see at startup) so that
# frame seeking is exact.
from vssource import BestSource


# --- Setup -------------------------------------------------------------------

# "core" is the VapourSynth engine. Every built-in filter (resize, etc.) is
# called through it.
core = vs.core

# Size of VapourSynth's frame cache, in megabytes. A bigger cache lets it keep
# more frames in memory so work isn't redone. 4096 = 4 GB. Safe on most GPUs.
core.max_cache_size = 4096


# --- Step 1: Load the video --------------------------------------------------

# Opens the input file. "clip" is a lazy pipeline: nothing is actually decoded
# yet, frames are only produced when something downstream asks for them.
clip = BestSource.source("input.mp4")


# --- Step 2: Convert to RGB half-float --------------------------------------

# Video is normally stored as YUV (brightness + color channels). The AI models
# need RGB, so we convert here.
#   format=vs.RGBH      -> RGB stored as 16-bit floats ("(H)alf" precision).
#                          Half precision is much faster on the GPU and uses
#                          half the memory bandwidth. This is a major speedup
#                          (RGBS would be 32-bit float: 2x slower or more)
#   matrix_in_s="709"   -> tells the converter the source uses the BT.709
#                          color standard (the usual one for HD video), so the
#                          colors come out right.
# Note there is NO resizing here: Real-ESRGAN does the upscaling itself, and
# gets the best results when fed the original resolution.
clip = core.resize.Bicubic(clip, format=vs.RGBH, matrix_in_s="709")

# Safety check: stop immediately with a clear message if the clip isn't RGBH.
# Real-ESRGAN refuses other formats, and this makes the failure easy to
# understand. It does nothing when everything is fine.
assert clip.format.id == vs.RGBH, clip.format.name  # fails loudly if conversion is wrong


# --- Step 3: Upscale 2x with Real-ESRGAN ------------------------------------

# Parameters:
#   model=RealESRGANModel.RealESRGAN_x2plus
#       The pretrained network used. "x2plus" upscales by exactly 2x and is a
#       general-purpose, high-quality (but heavy) model. The 2x scale comes
#       from the model itself.
#   device_index=0
#       Which GPU to use. 0 = the first (on most machines, the only one).
#   num_streams=2
#       How many frames the GPU works on in parallel. More streams can keep the
#       GPU busier, but past a point it stops helping. Worth trying 1-4 if you
#       want to tune speed.
#   trt=True
#       Use NVIDIA TensorRT: the model is compiled into an optimized GPU
#       engine on first run (slow, takes minutes, then cached), and every run
#       after that is much faster. This is the biggest single speedup (10x).
#       It works correctly for Real-ESRGAN here.
#   auto_download=True
#       Download the model weights automatically if they aren't present yet.
clip = realesrgan(clip, model=RealESRGANModel.RealESRGAN_x2plus, device_index=0,
                  num_streams=2, trt=True, auto_download=True)


# --- Step 4: Double the frame rate with RIFE --------------------------------

# Parameters:
#   factor_num=2
#       Frame rate multiplier: one new frame is invented between each pair of
#       real frames, so 25 fps -> 50 fps. (For a fixed target like 60 fps you
#       would use fps_num=60, fps_den=1 instead.)
#   model="4.25"
#       Which version of the RIFE network to use.
#   sc=False
#       Scene-change detection is off (it needs an extra plugin we didn't
#       install). Side effect: at hard cuts, RIFE blends the two scenes for
#       one frame, causing a brief ghosted frame.
#   trt=False
#       IMPORTANT: TensorRT is deliberately OFF for RIFE. With trt=True the
#       invented frames came out with large blobby noise (the TensorRT engine
#       gave wrong results for this model on my hardware). Plain PyTorch
#       with fp16 input is correct, and still fast. Leaving trt as False.
clip = vsrife.rife(clip, factor_num=2, model="4.25", sc=False, trt=False)


# --- Step 5: Convert back to YUV for encoding -------------------------------

# Video encoders want YUV, so we convert back from RGB.
#   format=vs.YUV420P10  -> YUV, 4:2:0 chroma subsampling (the standard layout
#                           for consumer video), 10 bits per channel. 10-bit
#                           gives smoother gradients than the 8-bit source and
#                           is worth keeping since we are re-encoding anyway.
#   matrix_s="709"       -> same BT.709 color standard as in Step 2, applied in
#                           reverse so colors match the original.
clip = core.resize.Bicubic(clip, format=vs.YUV420P10, matrix_s="709")


# --- Step 6: Hand off the result --------------------------------------------

# Marks this clip as the script's output. vspipe reads frames from here and
# pipes them to ffmpeg. Without this line, the script produces nothing.
clip.set_output()
