# launch_common.sh  (sourced, not executed directly)

LLAMA_SERVER=./build/bin/llama-server

COMMON_ARGS="
  --offline
  --host 0.0.0.0
  --port 8080
  --fit on
  --jinja
  --flash-attn on
  --presence-penalty 0.0
  --repeat-penalty 1.0
"

GEMMA_ARGS="
  --hf-repo unsloth/gemma-4-E4B-it-GGUF
  --ctx-size 65536
  --temp 1.0
  --min-p 0.05
  --top-k 64
  --top-p 0.95
  --parallel 2
"

QWEN_ARGS="
  --hf-repo unsloth/Qwen3.6-35B-A3B-GGUF
  --ctx-size 32768
  --temp 0.6
  --min-p 0.0
  --top-k 20
  --top-p 0.95
  --parallel 1
"
