#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

if [ "$PWD" == "$HOME" ] ; then
    echo '[!] You run from your $HOME folder. pi.dev/its plugins will be able'
    echo '[!] to write in your dot files/folders (.bashrc, etc).'
    echo '[!]'
    echo '[!] Are you sure? Press Ctrl-c to cancel, otherwise hit ENTER.'
    read ANS
fi

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

OUR_RANDOM_PID=$$
SOCK="$HOME/llama.sock.$OUR_RANDOM_PID"

# Shared parser expects die/usage to exist
die()      { echo "error: $*" >&2; exit 1; }
usage() {
  cat >&2 <<'EOF'
Usage: pi.isolated.sh [--port PORT] [isolate.sh OPTIONS] [-- pi OPTIONS]
See isolate.sh --help for full isolate.sh option documentation.
PORT defaults to 8081.
EOF
  exit 2
}

# Wrapper-specific: --port for the host-side model endpoint.
# The inner sandbox socat always listens on 8081; this only changes
# what the host-side relay (and curl) talk to.
# --port can appear anywhere in the argument list.
PORT=8081
_rest=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port=*) PORT="${1#*=}"; shift ;;
        --port)  [[ $# -ge 2 ]] || usage; PORT="$2"; shift 2 ;;
        *)       _rest+=("$1"); shift ;;
    esac
done
set -- "${_rest[@]}"

# Make this point to your locally running model (or SSH-forwarded remote):
URL=http://127.0.0.1:$PORT

# Reuse shared parser for isolate.sh options
. "$SCRIPT_DIR/parse-isolation-options-common.sh"

# (a) Check/Launch host relay
if ! pgrep -f "socat UNIX-LISTEN:$SOCK,fork TCP:127.0.0.1:$PORT" >/dev/null; then
    echo "[+] Launching host socat relay to 127.0.0.1:$PORT..."
  echo "[+] Launching host socat relay..."
  rm -f "$SOCK"
  socat UNIX-LISTEN:"$SOCK",fork TCP:127.0.0.1:$PORT 2>/dev/null &
  SOCAT_PID=$!
  # Give it a moment to bind
  sleep 0.2
fi
trap '[[ -n ${SOCAT_PID:-} ]] && kill "$SOCAT_PID" 2>/dev/null' EXIT

# Query model info
MODELS_JSON=$(curl -sf $URL/v1/models)
# MODELS_JSON=$(curl -sf http://127.0.0.1:8081/v1/models)   # direct to llama-server
if [ $? -ne 0 ] || [ -z "$MODELS_JSON" ]; then
  echo "[-] Could not reach model server at $URL - is it running?"
  exit 1
fi


# Try to get props for context size
PROPS_JSON=$(curl -sf $URL/props || echo "{}")
# PROPS_JSON=$(curl -sf http://127.0.0.1:8081/props || echo "{}")  # direct to llama-server

read -r MODEL_ID CTX_SIZE < <(python3 -c "
import sys, json
try:
    models_data = json.loads(sys.argv[1])
    props_data = json.loads(sys.argv[2])

    model = models_data['data'][0]
    model_id = model['id']

    # 1. Try vLLM style
    ctx_size = model.get('max_model_len')
    if ctx_size is None:
        ctx_size = model.get('meta', {}).get('n_ctx')

    # 2. Try llama.cpp nested style (default_generation_settings -> n_ctx)
    if ctx_size is None:
        ctx_size = props_data.get('default_generation_settings', {}).get('n_ctx')

    # 2. Try llama.cpp ds4 style
    if ctx_size is None:
        try:
            ctx_size = model.get('context_length')
        except:
            ctx_size = None

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

sleep 1

mkdir -p ~/.pi/agent/

cat > ~/.pi/agent/models.json << EOF
{
  "providers": {
    "local-vllm": {
      "baseUrl": "http://127.0.0.1:8080/v1",
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
ISOLATE_ARGS=(--rw "$PWD" --rw "$HOME/.pi/" --rw "$SOCK")
for s in "${SERVERS_FILES[@]}"; do ISOLATE_ARGS+=(--servers "$s"); done
[[ -n "$DNS_CSV" ]] && ISOLATE_ARGS+=(--dns "$DNS_CSV")
for p in "${RW_PATHS[@]}"; do ISOLATE_ARGS+=(--rw "$p"); done
for p in "${HIDE_PATHS[@]}"; do ISOLATE_ARGS+=(--hide "$p"); done
[[ -n "$IFACE" ]] && ISOLATE_ARGS+=(--iface "$IFACE")
(( PRIVATE_DEV )) || ISOLATE_ARGS+=(--host-dev)

APP_ARGS=$(printf '%q ' "${APP[@]}")
INNER_CMD="socat TCP-LISTEN:8080,fork UNIX-CONNECT:\"$SOCK\" 2>/dev/null & pi --offline $APP_ARGS"

if [[ " ${APP[*]} " == *" -p "* || " ${APP[*]} " == *" --print "* ]]; then
    isolate.sh "${ISOLATE_ARGS[@]}" bash -c "$INNER_CMD"
else
    isolate.sh "${ISOLATE_ARGS[@]}" \
        tmux new-session -A -s "pi_session_${OUR_RANDOM_PID}" "bash -c '$INNER_CMD'"
fi
