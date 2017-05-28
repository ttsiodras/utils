#!/usr/bin/env python3
import os

# !_TAG_FILE_SORTED 0
cmd = """\
gnatxref -v $(find . -type f -iname '*.ali') | LC_COLLATE=C sort
"""
fullPaths = {}
for path in os.popen("find . -type f -iname '*.ad[sb]'").readlines():
    parts = path.strip().split("/")
    fullPaths[parts[-1]] = "/".join(parts[:-1])

for line in os.popen(cmd).readlines():
    symbol, filename, lineno = line.strip().split("\t")
    try:
        filename = fullPaths[filename] + "/" + filename
        print("\t".join([symbol, filename, lineno]))
    except:
        pass
