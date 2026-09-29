#!/usr/bin/env python3
"""pi session .jsonl -> markdown.   Usage: pilog.py <session.jsonl> [out.md]"""
import json, os, re, signal, sys

try:                                     # so `pilog.py x.jsonl | less` doesn't spam BrokenPipeError
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):
    pass

ROLES = {"toolResult": "Tool result"}    # everything else is just role.title()


def clip(text, limit=20):                # keep one huge tool result from flooding the file
    lines = text.split("\n")
    if len(lines) > limit:
        lines = lines[:limit] + ["[%d more lines]" % (len(lines) - limit)]
    return "\n".join(lines)


def fence(text, lang="text"):
    # Tilde runs inside the body would close the block early, so out-longest them.
    longest = max([len(m.group(0)) for m in re.finditer(r"~+", text)] or [0])
    fens = "~" * max(3, longest + 1)
    return "%s%s\n%s\n%s\n" % (fens, lang, text, fens)


def blocks(c):
    if isinstance(c, str):
        yield "text", c
    elif isinstance(c, list):
        for b in c:
            t = b.get("type")
            if t == "text":
                yield "text", b.get("text", "")
            elif t == "thinking":
                yield "thinking", b.get("thinking", "")
            elif t == "toolCall":
                args = json.dumps(b.get("arguments"), ensure_ascii=False, indent=1)
                if len(args) > 2000:     # truncate *inside* the fence, never cut the fence off
                    args = args[:2000] + "\n[... arguments truncated]"
                yield "tool", "**tool** `%s`\n\n%s" % (b.get("name"), fence(args))
            elif t == "image":
                yield "text", "[image: %s]" % b.get("mimeType", "?")


def show(text, indent=""):
    print("\n".join(indent + l for l in clip(text).split("\n")))


if len(sys.argv) < 2:
    sys.exit("usage: pilog.py <session.jsonl> [out.md]")
path = sys.argv[1]
if not os.path.isfile(path):
    sys.exit("pilog.py: no such file: %s" % path)

out = sys.stdout
if len(sys.argv) > 2:
    try:
        out = open(sys.argv[2], "w", encoding="utf-8")
    except OSError as e:
        sys.exit("pilog.py: cannot write %s: %s" % (sys.argv[2], e.strerror))
real_stdout = sys.stdout
sys.stdout = out

try:
    with open(path, encoding="utf-8", errors="replace") as f:
        first = f.readline()
        try:
            hdr = json.loads(first) if first.strip() else {}
        except ValueError:
            hdr = {}
        print("# %s\n\n- id: `%s`\n- cwd: `%s`\n- start: %s\n"
              % (os.path.basename(path), hdr.get("id"), hdr.get("cwd"), hdr.get("timestamp")))

        n = 0
        f.seek(0)
        for line in f:
            n += 1
            try:
                e = json.loads(line)
            except ValueError:
                continue
            t = e.get("type")
            when = (e.get("timestamp") or "")[11:19]
            if t == "session":
                continue
            if t == "model_change":
                print("\n*model -> %s/%s*" % (e.get("provider"), e.get("modelId")))
            elif t == "thinking_level_change":
                print("\n*thinking -> %s*" % e.get("thinkingLevel"))
            elif t == "compaction":
                print("\n*compaction (%s tokens)*" % e.get("tokensBefore"))
            elif t == "message":
                m = e.get("message") or {}
                role = m.get("role") or "?"
                if role == "system":
                    continue
                print("\n## %s (%s)\n" % (ROLES.get(role, role.title()), when))
                for kind, body in blocks(m.get("content")):
                    if kind == "thinking":
                        flat = " ".join(body.split())
                        print("> thinking: " + flat[:300] + ("..." if len(flat) > 300 else ""))
                    elif kind == "tool":
                        print(body)
                    elif role == "toolResult":  # fenced: keeps `$`/`\` out of pandoc's TeX math
                        print(fence(clip(body)))
                    else:
                        show(body)
                if m.get("isError"):
                    print("**(error)**")

        print("\n---\n%d entries" % n)
finally:
    if out is not real_stdout:
        out.close()
