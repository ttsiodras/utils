#!/bin/bash
# Pick local AI model + backend, then exec llama-server on $LLAMA_PORT.
#
# Deliberately thin: the flags and the reasoning behind them live in
# launch_common.sh, including a MEASUREMENTS block with the protocol.  This
# script only chooses which of those sets to use and hands over to the server.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
source ./launch_common.sh

# Model menu.  The 35B window is small on purpose: its KV cache is allocated
# from ordinary pageable memory rather than from the iGPU's fixed-size Vulkan
# heap, which is what makes a 32k window possible here (see the arena note in
# launch_common.sh).
echo "Model:"
echo "  1) Qwen3.5 9B Q4_K_M       (best pp, worst tg; fits the Vulkan heap)"
echo "  2) Qwen3.6 35B A3B Q3_K_S  (best tg; 32k ctx, KV outside the Vulkan heap)"
read -rp "Choice: " model_choice

# Backend menu.  Only the 35B has a real choice: its weights do not fit the
# fixed-size Vulkan heap, so all three splits are meaningfully different.  The
# 9B fits whole and its CPU path is a wash per turn, so it is GPU-only.
echo "Backend:"
echo "  1) Vulkan   (fastest prompt processing)"
echo "  2) SyCL     (middle ground)"
echo "  3) CPU only (fastest token generation; model 2 only)"
read -rp "Choice: " backend_choice

case $model_choice in
  1) MODEL_ARGS="$QWEN_ARGS" ;;
  2) MODEL_ARGS="$QWEN36_ARGS" ;;
  *) echo "[!] Invalid model choice"; exit 1 ;;
esac

# Device policy is per model: the 35B asks qwen36_device_args() (which also
# knows about the CPU-only path), the 9B just takes a device.
if [ "$model_choice" = 2 ]; then
    DEVICE_ARGS="$(qwen36_device_args "$backend_choice")" || { echo "[!] Invalid backend choice"; exit 1; }
else
    case $backend_choice in
      1) DEVICE_ARGS="--device vulkan0" ;;
      2) DEVICE_ARGS="--device SYCL0" ;;
      3) echo "[!] CPU backend is only wired up for the 35B (model 2)"; exit 1 ;;
      *) echo "[!] Invalid backend choice"; exit 1 ;;
    esac
fi

# Echo the exact argv first: it is the only record of what was run once the
# server takes over the terminal.  The pi line matters because pi's sandbox
# dials its own 8080, not $LLAMA_PORT.
echo "[+] Launching $LLAMA_SERVER $DEVICE_ARGS $COMMON_ARGS $MODEL_ARGS"
echo "[+] pi (sandboxed):  ~/bin/pi.isolated.sh --port $LLAMA_PORT"

# exec, so Ctrl-C and the shell's job control go straight to llama-server.
exec $LLAMA_SERVER $DEVICE_ARGS $COMMON_ARGS $MODEL_ARGS
