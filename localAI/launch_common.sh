# launch_common.sh  (sourced, not executed directly)

LLAMA_SERVER=/home/stablediffusion/llama.cpp/build/bin/llama-server

COMMON_ARGS="
  --offline
  --host 127.0.0.1
  --port 8080
  --fit on
  --jinja
  --flash-attn on
  --presence-penalty 0.0
  --repeat-penalty 1.0
"

GEMMA_ARGS="
  --hf-repo unsloth/gemma-4-E4B-it-GGUF:Q4_0
  --ctx-size 65536
  --temp 1.0
  --min-p 0.05
  --top-k 64
  --top-p 0.95
  --parallel 2
"
