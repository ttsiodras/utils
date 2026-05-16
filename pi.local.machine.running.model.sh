#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Nastiness.
#
# When I use isolate.sh (see last line in this script) - which I HAVE to do,
# since we live in days of daily kernel exploits and supply chain attacks!
# ...well, I suffer from this:
# My locally running model listens at localhost:PORT.  firejail (which is what
# my isolate.sh uses) creates a new network namespace; so my machine's
# localhost becomes invisible (the new network namespace has its own lo!)
#
# So... we tunnel via a pair of socats; over a UNIX domain socket.

SOCK="$HOME/llama.sock"

# Make this point to your locally running model:
URL=http://127.0.0.1:8080

# (a) Check/Launch host relay
if ! pgrep -f "socat UNIX-LISTEN:$SOCK,fork TCP:127.0.0.1:8080" >/dev/null; then
  echo "[+] Launching host socat relay..."
  rm -f "$SOCK"
  socat UNIX-LISTEN:"$SOCK",fork TCP:127.0.0.1:8080 &
  SOCAT_PID=$!
  # Give it a moment to bind
  sleep 0.2
fi
trap '[[ -n ${SOCAT_PID:-} ]] && kill "$SOCAT_PID" 2>/dev/null' EXIT

# Query model info
MODELS_JSON=$(curl -sf $URL/v1/models)
if [ $? -ne 0 ] || [ -z "$MODELS_JSON" ]; then
  echo "[-] Could not reach model server at $URL - is it running?"
  exit 1
fi

# Try to get props for llama.cpp context size
PROPS_JSON=$(curl -sf $URL/props || echo "{}")

read -r MODEL_ID CTX_SIZE < <(python3 -c "
import sys, json
try:
    models_data = json.loads(sys.argv[1])
    props_data = json.loads(sys.argv[2])
    
    model = models_data['data'][0]
    model_id = model['id']
    
    # 1. Try vLLM style
    ctx_size = model.get('max_model_len')
    
    # 2. Try llama.cpp nested style (default_generation_settings -> n_ctx)
    if ctx_size is None:
        ctx_size = props_data.get('default_generation_settings', {}).get('n_ctx')
        
    # 3. Try llama.cpp top-level style (n_ctx)
    if ctx_size is None:
        ctx_size = props_data.get('n_ctx')
        
    # 4. Fallback
    if ctx_size is None:
        ctx_size = 8192
        
    print(f'{model_id} {int(ctx_size)}')
except Exception:
    print('unknown-model 8192')
" "$MODELS_JSON" "$PROPS_JSON")

MAX_TOKENS=$CTX_SIZE
echo "[+] Model: $MODEL_ID  |  Context: $CTX_SIZE  |  MaxTokens: $MAX_TOKENS"

mkdir -p ~/.pi/agent/

cat > ~/.pi/agent/models.json << EOF
{
  "providers": {
    "local-vllm": {
      "baseUrl": "$URL/v1",
      "api": "openai-completions",
      "apiKey": "dummy",
      "compat": {
        "supportsDeveloperRole": false,
        "supportsReasoningEffort": false
      },
      "models": [
        {
          "id": "$MODEL_ID",
          "name": "$MODEL_ID (local vllm)",
          "reasoning": false,
          "input": ["text", "image"],
          "contextWindow": $CTX_SIZE,
          "maxTokens": $MAX_TOKENS,
          "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 }
        }
      ]
    }
  }
}
EOF

# (b) Launch isolate.sh with internal socat bridge
# We wrap the command in bash -c to launch socat in the background before npx pi
isolate.sh --rw "$PWD" --rw "$HOME/.pi/" --rw "$SOCK" \
    bash -c "socat TCP-LISTEN:8080,fork UNIX-CONNECT:\"$SOCK\" & npx pi \"\$@\"" -- "$@"
