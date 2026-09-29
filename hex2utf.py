#!/usr/bin/env python3
r'''
This is a quick hack to dump error logs written in e.g. PHP error logs
(they use the \xDE\xAD\xBE\xEF encoding).

Reads the given file, or stdin, and expands \xNN - plus the usual
\n, \t, \\ and friends - into the raw bytes they stand for.
'''

import sys

_SIMPLE = {
    'n': 0x0A, 't': 0x09, 'r': 0x0D, 'a': 0x07, 'b': 0x08,
    'f': 0x0C, 'v': 0x0B, '\\': 0x5C, "'": 0x27, '"': 0x22,
}
_HEX = b'0123456789abcdefABCDEF'


def unescape(data):
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        if data[i:i + 1] == b'\\' and i + 1 < n:
            nxt = data[i + 1:i + 2]
            if nxt == b'x' and i + 4 <= n and all(c in _HEX for c in data[i + 2:i + 4]):
                out.append(int(data[i + 2:i + 4], 16))
                i += 4
                continue
            ch = nxt.decode('latin-1')
            if ch in _SIMPLE:
                out.append(_SIMPLE[ch])
                i += 2
                continue
        out.append(data[i])
        i += 1
    return bytes(out)


if __name__ == '__main__':
    source = open(sys.argv[1], 'rb') if len(sys.argv) > 1 else sys.stdin.buffer
    with source:
        for line in source:
            sys.stdout.buffer.write(unescape(line.rstrip(b'\n')) + b'\n')
