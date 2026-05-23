# launch.sh
source ./launch_common.sh

echo "Forge guardrails:"
echo "  1) OFF"
echo "  2) ON"
read -rp "Choice: " guardrails_choice

echo "Model:"
echo "  1) Gemma4 E4B"
echo "  2) Qwen3.5 9B"
read -rp "Choice: " model_choice

echo "Backend:"
echo "  1) Vulkan"
echo "  2) ROCM"
read -rp "Choice: " backend_choice

case $model_choice in
  1) MODEL_ARGS="$GEMMA_ARGS" ;;
  2) MODEL_ARGS="$QWEN_ARGS" ;;
  *) echo "[!] Invalid model choice"; exit 1 ;;
esac

case $backend_choice in
  1) DEVICE="vulkan0" ;;
  2) DEVICE="ROCM0" ;;
  *) echo "[!] Invalid backend choice"; exit 1 ;;
esac

case $guardrails_choice in
  1)
      COMMON_ARGS="$(echo "$COMMON_ARGS" | sed 's,8081,8080,')" ;
      echo "[+] Launching $LLAMA_SERVER --device $DEVICE $COMMON_ARGS $MODEL_ARGS" ;
      exec $LLAMA_SERVER --device $DEVICE $COMMON_ARGS $MODEL_ARGS ;;
esac

$LLAMA_SERVER --device $DEVICE $COMMON_ARGS $MODEL_ARGS &
echo "[+] Launching $LLAMA_SERVER --device $DEVICE $COMMON_ARGS $MODEL_ARGS &"
LLAMA_PID=$!

# Wait for llama-server to be ready
echo "[+] Waiting for llama-server..."
until curl -sf http://127.0.0.1:8081/health >/dev/null 2>&1; do sleep 0.5; done
echo "[+] llama-server ready, starting forge proxy..."

# pip install forge-guardrails
.venv/bin/python -m forge.proxy --backend-url http://127.0.0.1:8081 --port 8080 &
FORGE_PID=$!

trap 'kill $LLAMA_PID $FORGE_PID 2>/dev/null' EXIT INT TERM
echo "[+] Forge proxy on :8080 -> llama-server on :8081"
wait $LLAMA_PID
