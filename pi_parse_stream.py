#!/usr/bin/env python3
"""
Decodes the stream of json responses printed by the pi harness.
Used by get_subs_tmux.sh
"""
import json
import sys

for line in sys.stdin:
    try:
        msg = json.loads(line)
    except Exception:
        continue

    t = msg.get("type")

    # -------------------------
    # lifecycle (optional debug)
    # -------------------------
    if t in ("session", "agent_start", "agent_end",
             "turn_start", "turn_end"):
        continue

    # -------------------------
    # tool execution trace
    # -------------------------
    if t == "tool_execution_start":
        print(f"\n[tool execution start] {msg.get('toolName')}", flush=True)

    elif t == "tool_execution_update":
        continue

    elif t == "tool_execution_end":
        continue

    elif t == "toolResult":
        print(f"\n[tool result] {msg.get('toolName')} -> {msg.get('content')}", flush=True)

    # -------------------------
    # assistant message stream
    # -------------------------
    if t == "message_update":
        evt = msg.get("assistantMessageEvent", {})
        et = evt.get("type")

        # ---- thinking ----
        if et == "thinking_delta":
            print(evt.get("delta", ""), end="", flush=True)

        # ---- text ----
        elif et == "text_delta":
            print(evt.get("delta", ""), end="", flush=True)

        # ---- tool call (final structured form) ----
        elif et == "toolcall_start":
            tc = evt.get("partial", {}).get("content", [])
            for item in tc:
                if item.get("type") == "toolCall":
                    print(
                        f"\n\n[tool call] {item.get('name')} {item.get('arguments')}\n",
                        flush=True
                    )

        elif et == "toolcall_delta":
            # optional: usually noisy, but you can print if debugging
            continue

        elif et == "toolcall_end":
            tc = evt.get("toolCall", {})
            print(
                f"\n\n[tool call end] {tc.get('name')} {tc.get('arguments')}\n",
                flush=True
            )

print("")
