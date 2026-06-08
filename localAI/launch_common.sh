# launch_common.sh  (sourced, not executed directly)

LLAMA_SERVER=/home/stablediffusion/llama.cpp/build/bin/llama-server

COMMON_ARGS="
  --offline
  --host 127.0.0.1
  --port 8081
  -ngl 99
  --fit off
  --jinja
  --flash-attn on
  --presence-penalty 0.0
  --repeat-penalty 1.0
  --no-mmap
  --mlock
"

GEMMA_ARGS="
  --hf-repo google/gemma-4-12B-it-qat-q4_0-gguf:Q4_0
  --spec-draft-hf RachidAR/gemma-4-12B-it-qat-q4_0-MTP-assistant-gguf:Q4_0
  --spec-type draft-mtp
  --spec-draft-n-max 2
  --ctx-size 32768
  --temp 1.0
  --min-p 0.05
  --top-k 64
  --top-p 0.95
  --parallel 1
"
# --no-mmproj

# Qwen3.5 recommended params from model card:
# thinking mode:  temp=0.6, top-k=20, top-p=0.95, min-p=0.0
QWEN_ARGS="
  --hf-repo unsloth/Qwen3.5-9B-MTP-GGUF:Q4_K_M
  --ctx-size 65536
  --temp 0.6
  --min-p 0.0
  --top-k 20
  --top-p 0.95
  --parallel 1
"

# Half the pp/s, 8.6 => 6.2 tg/s
# --spec-type draft-mtp --spec-draft-n-max 3

