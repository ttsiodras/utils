# launch.sh
source ./launch_common.sh

echo "Model:"
echo "  1) Gemma4 E4B"
echo "  2) Qwen3.5 9B"
read -rp "Choice: " model_choice

echo "Backend:"
echo "  1) ROCM"
echo "  2) Vulkan"
read -rp "Choice: " backend_choice

case $model_choice in
  1) MODEL_ARGS="$GEMMA_ARGS" ;;
  2) MODEL_ARGS="$QWEN_ARGS" ;;
  *) echo "Invalid model choice"; exit 1 ;;
esac

case $backend_choice in
  1) DEVICE="ROCM0" ;;
  2) DEVICE="vulkan0" ;;
  *) echo "Invalid backend choice"; exit 1 ;;
esac

echo "Launching $DEVICE..."
exec $LLAMA_SERVER --device $DEVICE $COMMON_ARGS $MODEL_ARGS
