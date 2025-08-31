ffmpeg -hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -i "$1" \
  -vf "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc,format=nv12,hwupload" \
  -c:v hevc_vaapi -qp 23 /dev/shm/2x.mp4
