#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
if [ -z "$KITTY_PID" ]; then
    echo "[x] You are not inside kitty — pi depends on the Kitty protocol."
    read -rp "[-] Shall I launch kitty and run pi there? [Y/n] " ANS
    if [ "$ANS" = "n" ] || [ "$ANS" = "N" ]; then
        echo "[-] Aborting."
        exit 1
    else
        kitty bash "$0" "$@" &
        exit 0
    fi
fi

# Query vllm for the currently loaded model
MODELS_JSON=$(curl -sf http://localhost:8080/v1/models)
if [ $? -ne 0 ] || [ -z "$MODELS_JSON" ]; then
  echo "[-] Could not reach vllm at localhost:8080 — is it running?"
  exit 1
fi

read -r MODEL_ID CTX_SIZE < <(echo "$MODELS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
model = data['data'][0]
model_id = model['id']
# vllm exposes max_model_len directly on the model object
ctx_size = model.get('max_model_len', 8192)
print(model_id, ctx_size)
")

MAX_TOKENS=$CTX_SIZE
echo "[+] Model: $MODEL_ID  |  Context: $CTX_SIZE  |  MaxTokens: $MAX_TOKENS"

TMPDIR_PI=$(mktemp -d)
cat > "$TMPDIR_PI/models.json" << EOF
{
  "providers": {
    "local-vllm": {
      "baseUrl": "http://172.17.0.1:8080/v1",
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

echo "[-] Remember to:"
echo "    socat TCP-LISTEN:8080,reuseaddr,fork,bind=172.17.0.1 TCP:localhost:8080"

cat > "$TMPDIR_PI/pi.AGENTS.md" << 'OEF'
When spawning subagents for tasks that don't need an immediate result, always use `run_in_background: true`.
OEF

docker run --network=restricted_net \
  -w "$PWD" \
  --rm \
  -v "$PWD:$PWD" \
  -v "$TMPDIR_PI/pi.AGENTS.md":"/home/$(id -un)/.pi/agent/AGENTS.md:ro" \
  -v "$TMPDIR_PI/models.json":"/home/$(id -un)/.pi/agent/models.json:ro" \
  -it pi
rm -rf "$TMPDIR_PI"
