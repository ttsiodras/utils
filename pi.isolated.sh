#!/bin/bash
# pi.isolated2.sh — like pi.isolated.sh, but model capabilities (in particular
# the *thinking levels*, which differ per model family: gpt-oss, deepseek-r1,
# qwen3, GLM, gemini, ...) are auto-detected by the embedded Python detector
# (fully standalone - no external files) instead
# of being hardcoded.  Use --probe for a live probe of which reasoning wire
# format the server actually honours.
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

if [ "$PWD" == "$HOME" ] ; then
    echo '[!] You run from your $HOME folder. pi.dev/its plugins will be able'
    echo '[!] to write in your dot files/folders (.bashrc, etc).'
    echo '[!]'
    echo '[!] Are you sure? Press Ctrl-c to cancel, otherwise hit ENTER.'
    read ANS
fi

# Nastiness (same as pi.isolated.sh):
# locally running model listens at localhost:PORT; firejail/isolate.sh makes
# the host's localhost invisible, so we tunnel via a pair of socats over a
# UNIX domain socket.

OUR_RANDOM_PID=$$
SOCK="$HOME/llama.sock.$OUR_RANDOM_PID"

# Shared parser expects die/usage to exist
die()      { echo "error: $*" >&2; exit 1; }
usage() {
  cat >&2 <<'EOF'
Usage: pi.isolated2.sh [OPTIONS] [-- pi OPTIONS]

Model detection options:
  --port PORT              Local model port (default 8081)
  --url URL                Full base URL of an OpenAI-compatible server
                           (e.g. https://generativelanguage.googleapis.com/v1beta/openai/v1)
                           Skips the local socat tunnel.
  --api-key KEY            API key for --url (default: $GEMINI_API_KEY if set)
  --thinking auto|on|off   Force reasoning on/off (default: auto-detect)
  --thinking-format FMT    Force thinking wire format:
                           auto|openai|openrouter|deepseek|together|zai|qwen|qwen-chat-template
  --image / --no-image     Force vision on/off (default: auto-detect)
  --probe                  Live-probe the server (a few extra requests) to see
                           which reasoning style actually produces thinking, and
                           whether thinking can be switched off at all.
  --detect-only            Only detect + write models.json; do not launch pi.

Any other options are passed to isolate.sh (see isolate.sh --help),
arguments after -- are passed to pi.
EOF
  exit 2
}

PORT=8081
URL_FULL=""
API_KEY="${GEMINI_API_KEY:-}"
THINKING=auto
THINK_FORMAT=auto
IMAGE_MODE=auto
PROBE=0
DETECT_ONLY=0

_rest=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port=*)            PORT="${1#*=}"; shift ;;
        --port)              [[ $# -ge 2 ]] || usage; PORT="$2"; shift 2 ;;
        --url=*)             URL_FULL="${1#*=}"; shift ;;
        --url)               [[ $# -ge 2 ]] || usage; URL_FULL="$2"; shift 2 ;;
        --api-key=*)         API_KEY="${1#*=}"; shift ;;
        --api-key)           [[ $# -ge 2 ]] || usage; API_KEY="$2"; shift 2 ;;
        --thinking=*)        THINKING="${1#*=}"; shift ;;
        --thinking)          [[ $# -ge 2 ]] || usage; THINKING="$2"; shift 2 ;;
        --thinking-format=*) THINK_FORMAT="${1#*=}"; shift ;;
        --thinking-format)   [[ $# -ge 2 ]] || usage; THINK_FORMAT="$2"; shift 2 ;;
        --image)             IMAGE_MODE=on; shift ;;
        --no-image)          IMAGE_MODE=off; shift ;;
        --probe)             PROBE=1; shift ;;
        --detect-only)       DETECT_ONLY=1; shift ;;
        --help|-h)           usage ;;
        *)                   _rest+=("$1"); shift ;;
    esac
done
set -- "${_rest[@]}"

# Reuse shared parser for isolate.sh options
. "$SCRIPT_DIR/parse-isolation-options-common.sh"

BASE_URL="${URL_FULL:-http://127.0.0.1:$PORT}"
USE_TUNNEL=1
[[ -n "$URL_FULL" ]] && USE_TUNNEL=0

# (a) Host relay (only for a locally served model on 127.0.0.1:$PORT)
if (( USE_TUNNEL )); then
  if ! pgrep -f "socat UNIX-LISTEN:$SOCK,fork TCP:127.0.0.1:$PORT" >/dev/null; then
    echo "[+] Launching host socat relay to 127.0.0.1:$PORT..."
    rm -f "$SOCK"
    socat UNIX-LISTEN:"$SOCK",fork TCP:127.0.0.1:$PORT 2>/dev/null &
    SOCAT_PID=$!
    sleep 0.2
  fi
  trap '[[ -n ${SOCAT_PID:-} ]] && kill "$SOCAT_PID" 2>/dev/null; [[ -n ${SOCAT_PID:-} ]] && rm -f "$SOCK"' EXIT
fi

mkdir -p ~/.pi/agent/

# (b) Auto-detect model capabilities and write models.json
DETECT_ARGS=(--base-url "$BASE_URL"
             --output "$HOME/.pi/agent/models.json"
             --thinking "$THINKING"
             --thinking-format "$THINK_FORMAT"
             --image-mode "$IMAGE_MODE")
if (( USE_TUNNEL )); then
    # pi inside the sandbox talks to the inner socat, which listens on 8080.
    DETECT_ARGS+=(--sandbox-base-url "http://127.0.0.1:8080")
else
    DETECT_ARGS+=(--sandbox-base-url "$URL_FULL")
fi
(( PROBE )) && DETECT_ARGS+=(--probe)
[[ -n "$API_KEY" ]] && DETECT_ARGS+=(--api-key "$API_KEY")

# ---- embedded detector (standalone; no external .py needed) ----
python3 - "${DETECT_ARGS[@]}" <<'PYDET'
#!/usr/bin/env python3
"""
pi_isolated_detect.py — auto-detect capabilities of an OpenAI-compatible
model server (vLLM, llama.cpp, LM Studio, Google OpenAI-compat, ...) and
emit ~/.pi/agent/models.json for pi.

Detects / derives:
  * model id, context window, max tokens
  * whether the model is a reasoning model
  * which thinking "wire format" the server accepts (openai reasoning_effort,
    deepseek thinking{}, qwen chat_template_kwargs.enable_thinking, zai, together)
  * which pi thinking levels (off/minimal/low/medium/high/xhigh) make sense
    for the model family (each family differs!)
  * vision (image) input support

Strategy:
  1. Model-family table (name patterns) -> per-family thinkingLevelMap etc.
  2. Server hints (/props of llama.cpp: parse_reasoning, model_path, ...)
  3. Optional live probe (--probe): send one short completion per wire style
     and see which style actually yields reasoning content; also check whether
     "off" is possible (always-thinking models get "off": null).

Everything can be overridden from the command line.
"""

import argparse
import http.client
import json
import re
import socket
import sys
import urllib.error
import urllib.request

LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh"]

# ---------------------------------------------------------------------------
# Model-family table.
# Each entry: (family, regex, reasoning, thinking_format,
#              supports_reasoning_effort, level_map, requires_reasoning_content,
#              vision_hint)
# level_map only lists NON-default entries:
#   omitted key        -> level supported, provider default mapping
#   "level": "value"   -> level supported, send "value" to provider
#   "level": None      -> level unsupported (hidden in pi UI)
# ---------------------------------------------------------------------------
FAMILIES = [
    ("gpt-oss",       r"gpt[-_]oss",
        True, "openai", True,
        {"off": None, "xhigh": None},          # supports minimal/low/medium/high only
        False, False),

    ("deepseek-r1",   r"deepseek[-_]r1|\br1[-_]distill\b|deepseek[-_]oss",
        True, "deepseek", True,
        {"off": None,                           # R1 always thinks
         "minimal": "low", "low": "low", "medium": "medium",
         "high": "high", "xhigh": "max"},
        True, False),

    ("deepseek",      r"deepseek",
        True, "deepseek", True,
        {"minimal": "low", "xhigh": "max"},     # V3-style: low/medium/high/max + off
        True, False),

    ("qwq",           r"qwq",
        True, "qwen-chat-template", True,
        {"off": None, "minimal": "low", "xhigh": "high"},   # always-thinking
        False, False),

    ("qwen3-thinking", r"qwen3?.*thinking|thinking.*qwen3?",
        True, "qwen-chat-template", True,
        {"off": None, "minimal": "low", "xhigh": "high"},   # always-thinking
        False, False),

    ("qwen3",         r"qwen[-_ ]?3",
        True, "qwen-chat-template", True,
        {"minimal": "low", "xhigh": "high"},    # hybrid: off via enable_thinking=false
        False, False),

    ("qwen",          r"qwen",
        False, None, False,
        None,
        False, False),

    ("glm-thinking",  r"glm[-_ ]?(4\.[56]|5)|chatglm.*think",
        True, "zai", True,
        {"minimal": "low", "xhigh": "high"},    # hybrid thinking
        False, False),

    ("glm",           r"glm|chatglm",
        True, "zai", True,
        {"minimal": "low", "xhigh": "high"},
        False, False),

    ("kimi-thinking", r"kimi.*think|k1\.5",
        True, "openai", True,
        {"off": None, "minimal": "low", "xhigh": "high"},
        False, False),

    ("phi-reason",    r"phi[-_]?\d+.*reason|deepseek.*phil",
        True, "openai", True,
        {"off": None, "minimal": "low", "xhigh": "high"},
        False, False),

    ("magistral",     r"magistral|mistral.*reason",
        True, "openai", True,
        {"off": None, "minimal": "low", "xhigh": "high"},
        False, False),

    ("gemini-pro",    r"gemini.*pro",
        True, "openai", True,
        {"off": None, "minimal": "low", "xhigh": "high"},   # Pro always thinks
        False, True),

    ("gemini-flash",  r"gemini.*flash",
        True, "openai", True,
        {"minimal": "low", "xhigh": "high"},
        False, True),

    ("gemma",         r"gemma",
        False, None, False,
        None,
        False, True),

    ("llama",         r"llama",
        False, None, False,
        None,
        False, False),
]

VISION_PATTERN = (r"\bvl\b|vision|\bvlm\b|omni|pixtral|internvl|minicpm[-_]v"
                  r"|gemma[-_]3|llama[-_]4|glm[-_]4v|\bv\b(?=[-_])")

# Wire styles probed with --probe: (enable_payload, disable_payload)
PROBE_STYLES = {
    "openai":             ({"reasoning_effort": "high"},
                           {"reasoning_effort": "none"}),
    "qwen-chat-template": ({"chat_template_kwargs": {"enable_thinking": True}},
                           {"chat_template_kwargs": {"enable_thinking": False}}),
    "deepseek":           ({"thinking": {"type": "enabled"},
                            "reasoning_effort": "high"},
                           {"thinking": {"type": "disabled"}}),
    "zai":                ({"thinking": {"type": "enabled"}},
                           {"thinking": {"type": "disabled"}}),
    "together":           ({"reasoning": {"enabled": True}},
                           {"reasoning": {"enabled": False}}),
}

PROBE_PROMPT = ("A farmer has 17 sheep. All but 9 run away. A trader then "
                "trades them at 12 copper each and loses 38. How many are "
                "left, and was it a good deal? Reason step by step.")


def log(msg):
    print(msg, flush=True)


def http_json(url, api_key=None, timeout=15, payload=None):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def safe_get(base, path, api_key, timeout=10):
    try:
        return http_json(base.rstrip("/") + path, api_key, timeout)
    except Exception:
        return None


def extract_reasoning(msg):
    for k in ("reasoning", "reasoning_content", "reasoning_details"):
        v = msg.get(k)
        if isinstance(v, str) and v.strip():
            return True
    return False


def family_for(model_id):
    low = model_id.lower()
    for (fam, rx, reasoning, fmt, sre, lmap, rrc, vision) in FAMILIES:
        if re.search(rx, low):
            return dict(family=fam, reasoning=reasoning, fmt=fmt,
                        supports_reasoning_effort=sre,
                        level_map=dict(lmap) if lmap else None,
                        requires_reasoning_content=rrc, vision_hint=vision)
    # Fallback heuristic on the name alone
    reasoning = bool(re.search(r"think|reason|\br1\b|cot\b", low))
    return dict(family="generic", reasoning=reasoning,
                fmt="openai" if reasoning else None,
                supports_reasoning_effort=reasoning,
                level_map=None,
                requires_reasoning_content=False, vision_hint=False)


def detect_context(models_data, props):
    model = (models_data or {}).get("data", [{}])[0]
    ctx = (model.get("max_model_len")
           or model.get("meta", {}).get("n_ctx")
           or model.get("context_length"))
    if ctx is None and props:
        ctx = (props.get("default_generation_settings", {}).get("n_ctx")
               or props.get("n_ctx"))
    return int(ctx) if ctx else 8192


def safe_get_text(base, path, api_key, timeout=10):
    try:
        req = urllib.request.Request(base.rstrip("/") + path)
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode(errors="replace")
    except Exception:
        return None


def detect_vision(model_id, props, family, image_mode, metrics=None):
    if image_mode == "on":
        return True
    if image_mode == "off":
        return False
    # vLLM registers vllm:mm_cache_* / vllm:mm_inputs_* metrics only for
    # multimodal models -> authoritative, no name guessing needed.
    if metrics and re.search(r"vllm:mm_(cache|inputs|items)", metrics):
        return True
    low = model_id.lower()
    if re.search(VISION_PATTERN, low):
        return True
    if props:
        blob = json.dumps(props).lower()
        if "mmproj" in blob or "vision" in blob:
            return True
    return bool(family["vision_hint"])


class ProbeConnError(Exception):
    """Raised when --probe requests never get a valid HTTP answer.
    Covers the 'dead relay' trap: a socat/ssh -L listener on the port
    accepts connections even when the real model server behind it is
    down, so the client sees connection-reset / hang / empty-response
    instead of connection-refused. In that case we must abort, not
    silently fall back to table guesses."""


def _is_conn_error(e):
    # An actual HTTP response (even 4xx/5xx) proves the server is alive.
    if isinstance(e, urllib.error.HTTPError):
        return False
    # Empty/malformed status line or RemoteDisconnected: accepted socket,
    # no usable answer -> dead relay behind the listener.
    if isinstance(e, (http.client.BadStatusLine,
                      http.client.RemoteDisconnected,
                      http.client.IncompleteRead)):
        return True
    return isinstance(e, (urllib.error.URLError,
                          ConnectionError, socket.timeout, TimeoutError))


def probe(base, model_id, api_key):
    """Live-probe which wire style elicits reasoning, and whether off works.
    Returns (confirmed_fmt or None, thinking_always_on or None).
    Raises ProbeConnError if no probe request got a valid HTTP response."""
    answered = [0]  # count of requests that got any HTTP-level answer

    def ask(extra):
        payload = {"model": model_id, "temperature": 0,
                   "max_tokens": 128,
                   "messages": [{"role": "user", "content": PROBE_PROMPT}]}
        payload.update(extra)
        try:
            resp = http_json(base.rstrip("/") + "/v1/chat/completions",
                             api_key, timeout=60, payload=payload)
            answered[0] += 1
            return extract_reasoning(resp["choices"][0]["message"])
        except urllib.error.HTTPError:
            answered[0] += 1        # server answered -> alive; not thinking
            return False
        except Exception as e:
            if _is_conn_error(e):
                raise ProbeConnError(f"{type(e).__name__}: {e}")
            return None

    results = {style: ask(enable)
               for style, (enable, _dis) in PROBE_STYLES.items()}

    winners = [s for s, v in results.items() if v is True]
    if not winners:
        if answered[0] == 0 or all(v is None for v in results.values()):
            raise ProbeConnError("no probe request received a valid HTTP "
                                 "response (dead relay / wrong port?)")
        return None, None
    fmt = winners[0]
    # Does it keep thinking even when we try to disable it, via the same style?
    off = ask(PROBE_STYLES[fmt][1])
    always_on = True if off is True else None
    return fmt, always_on


def probe_vision(base, model_id, api_key):
    """Send a 1-pixel image; True if the server accepts multimodal content,
    False if it rejects it, None if inconclusive/unreachable."""
    px = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAf"
          "FcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    payload = {"model": model_id, "max_tokens": 8, "messages": [{
        "role": "user",
        "content": [{"type": "text", "text": "What is in this image?"},
                    {"type": "image_url", "image_url": {"url": px}}]}]}
    try:
        http_json(base.rstrip("/") + "/v1/chat/completions",
                  api_key, timeout=60, payload=payload)
        return True
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode(errors="replace").lower()
        except Exception:
            pass
        if e.code == 400 and any(w in body for w in
                                 ("image", "multimodal", "vision", "modality",
                                  "not supported", "do not support")):
            return False
        return None
    except Exception as e:
        if _is_conn_error(e):
            raise ProbeConnError(f"{type(e).__name__}: {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--sandbox-base-url", default="",
                    help="Base URL to write into models.json (may differ from "
                         "the URL we query, e.g. through the socat tunnel)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--thinking", choices=["auto", "on", "off"], default="auto")
    ap.add_argument("--thinking-format",
                    choices=["auto", "openai", "openrouter", "deepseek",
                             "together", "zai", "qwen", "qwen-chat-template"],
                    default="auto")
    ap.add_argument("--image-mode", choices=["auto", "on", "off"], default="auto")
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    models = safe_get(base, "/v1/models", args.api_key)
    if not models or not models.get("data"):
        log(f"[x] Could not read {base}/v1/models")
        sys.exit(1)
    model_id = models["data"][0]["id"]
    props = safe_get(base, "/props", args.api_key)          # llama.cpp
    version = safe_get(base, "/version", args.api_key)      # vLLM
    server = ("vllm" if version else
              "llama.cpp" if props else "openai-compatible")

    fam = family_for(model_id)
    ctx = detect_context(models, props)
    metrics = safe_get_text(base, "/metrics", args.api_key)
    vision = detect_vision(model_id, props, fam, args.image_mode, metrics)

    # llama.cpp hints override the name heuristic
    if props and props.get("parse_reasoning"):
        fam["reasoning"] = True
        if fam["fmt"] is None:
            fam["fmt"] = "openai"
            fam["supports_reasoning_effort"] = True

    # User overrides
    if args.thinking == "off":
        fam["reasoning"] = False
    elif args.thinking == "on":
        fam["reasoning"] = True
        if fam["fmt"] is None:
            fam["fmt"] = "openai"
            fam["supports_reasoning_effort"] = True
    if args.thinking_format != "auto" and fam["reasoning"]:
        fam["fmt"] = args.thinking_format

    # Live probe.  Any request that fails to reach the server at all (or
    # gets reset/hung/empty by a dead socat/ssh -L relay on the port)
    # aborts with non-zero exit instead of launching on table guesses.
    if args.probe:
        if fam["reasoning"]:
            log("[*] Live-probing reasoning wire styles (a few requests)...")
            try:
                fmt, always_on = probe(base, model_id, args.api_key)
            except ProbeConnError as e:
                log(f"[x] --probe: model server unreachable while probing "
                    f"thinking styles ({e})")
                log("[x] Aborting - not launching pi on unverified guesses.")
                sys.exit(1)
            if fmt:
                log(f"[+] Probe: server accepts thinking via '{fmt}'")
                fam["fmt"] = fmt
                if always_on:
                    log("[+] Probe: model keeps thinking even when disabled "
                        "-> hiding 'off'")
                    if fam["level_map"] is None:
                        fam["level_map"] = {}
                    fam["level_map"]["off"] = None
            else:
                log("[*] Probe: no style produced reasoning content; "
                    "keeping table guess")
        if args.image_mode == "auto":
            log("[*] Live-probing vision (1-pixel image request)...")
            try:
                v = probe_vision(base, model_id, args.api_key)
            except ProbeConnError as e:
                log(f"[x] --probe: model server unreachable while probing "
                    f"vision ({e})")
                log("[x] Aborting - not launching pi on unverified guesses.")
                sys.exit(1)
            if v is True:
                log("[+] Probe: server accepts image input -> vision on")
                vision = True
            elif v is False:
                log("[+] Probe: server rejects image input -> vision off")
                vision = False
            else:
                log("[*] Probe: vision result inconclusive; keeping "
                    "metrics/name guess")

    # Build models.json
    out_base = (args.sandbox_base_url or base).rstrip("/")
    provider_name = ("local-vllm" if "127.0.0.1" in out_base or "localhost" in out_base
                     else "openai-compatible")
    suffix = "local vllm" if provider_name == "local-vllm" else server

    model_cfg = {
        "id": model_id,
        "name": f"{model_id} ({suffix})",
        "input": ["text", "image"] if vision else ["text"],
        "contextWindow": ctx,
        "maxTokens": ctx,
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    }

    if fam["reasoning"]:
        compat = {
            "supportsStore": False,
            "supportsDeveloperRole": False,
            "supportsReasoningEffort": bool(fam["supports_reasoning_effort"]),
            "supportsUsageInStreaming": True,
            "maxTokensField": "max_tokens",
            "supportsStrictMode": False,
            "thinkingFormat": fam["fmt"],
        }
        if fam["fmt"] in ("deepseek", "zai") or fam["requires_reasoning_content"]:
            compat["requiresReasoningContentOnAssistantMessages"] = True
        model_cfg["reasoning"] = True
        model_cfg["compat"] = compat
        # Materialise the full level map so models.json is self-documenting:
        # pi's tristate says 'omitted = supported via provider default', but
        # that is invisible/fragile to read, so spell out every supported
        # effort level (level -> same-name effort) and keep nulls for the
        # unsupported ones.  'off' is only listed when explicitly disabled
        # (null) or explicitly mapped; support is conveyed by its absence.
        lm = dict(fam["level_map"]) if fam["level_map"] is not None else {}
        for lvl in ("minimal", "low", "medium", "high", "xhigh"):
            lm.setdefault(lvl, lvl)
        model_cfg["thinkingLevelMap"] = {k: lm[k] for k in LEVELS if k in lm}
    else:
        model_cfg["reasoning"] = False
        model_cfg["compat"] = {
            "supportsDeveloperRole": False,
            "supportsReasoningEffort": False,
        }

    cfg = {"providers": {provider_name: {
        "baseUrl": f"{out_base}/v1",
        "api": "openai-completions",
        "apiKey": args.api_key or "dummy",
        "models": [model_cfg],
    }}}

    with open(args.output, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")

    # Summary
    def enabled_levels():
        if not fam["reasoning"]:
            return []
        m = fam["level_map"] or {}
        return [l for l in LEVELS if m.get(l, "x") is not None]

    log(f"[+] Server: {server}  |  Model: {model_id}")
    log(f"[+] Context: {ctx}  |  Vision: {'yes' if vision else 'no'}")
    if fam["reasoning"]:
        log(f"[+] Reasoning: yes  |  family: {fam['family']}  |  "
            f"thinkingFormat: {fam['fmt']}  |  "
            f"reasoning_effort: {fam['supports_reasoning_effort']}")
        log(f"[+] Thinking levels: {', '.join(enabled_levels()) or '(default all)'}")
    else:
        log("[+] Reasoning: no")
    log(f"[+] Wrote {args.output}")


if __name__ == "__main__":
    main()
PYDET
rc=$?
if (( rc != 0 )); then
    die "Model detection failed against $BASE_URL (detector exit $rc) - is the model server really up (a socat/ssh relay can answer on the port even when the backend is dead)? Or override with --thinking / --thinking-format / --image. NOT launching pi."
fi

(( DETECT_ONLY )) && exit 0

# (c) Launch isolate.sh (with internal socat bridge when tunnelled)
ISOLATE_ARGS=(--rw "$PWD" --rw "$HOME/.pi/")
(( USE_TUNNEL )) && ISOLATE_ARGS+=(--rw "$SOCK")
for s in "${SERVERS_FILES[@]}"; do ISOLATE_ARGS+=(--servers "$s"); done
[[ -n "$DNS_CSV" ]] && ISOLATE_ARGS+=(--dns "$DNS_CSV")
for p in "${RW_PATHS[@]}"; do ISOLATE_ARGS+=(--rw "$p"); done
for p in "${HIDE_PATHS[@]}"; do ISOLATE_ARGS+=(--hide "$p"); done
[[ -n "$IFACE" ]] && ISOLATE_ARGS+=(--iface "$IFACE")
(( PRIVATE_DEV )) || ISOLATE_ARGS+=(--host-dev)

APP_ARGS=$(printf '%q ' "${APP[@]}")
if (( USE_TUNNEL )); then
    INNER_CMD="socat TCP-LISTEN:8080,fork UNIX-CONNECT:\"$SOCK\" 2>/dev/null & pi --offline $APP_ARGS"
else
    INNER_CMD="pi --offline $APP_ARGS"
fi

if [[ " ${APP[*]} " == *" -p "* || " ${APP[*]} " == *" --print "* ]]; then
    isolate.sh "${ISOLATE_ARGS[@]}" bash -c "$INNER_CMD"
else
    isolate.sh "${ISOLATE_ARGS[@]}" \
        tmux new-session -A -s "pi_session_${OUR_RANDOM_PID}" "bash -c '$INNER_CMD'"
fi
