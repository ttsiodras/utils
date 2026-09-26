#!/usr/bin/env python3
import re
import sys
import email.header as h
pat=re.compile(r"=\?[^?]+\?[bBqQ]\?[^?]+\?=")
for line in sys.stdin:
    print(pat.sub(lambda m: str(h.make_header(h.decode_header(m.group(0)))), line), end="")
