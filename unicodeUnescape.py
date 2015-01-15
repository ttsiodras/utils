#!/usr/bin/env python2
'''
A cmd-line filter for those pesky \u03b5\u03b3 strings...
e.g.

    $ wget -O - -q --post-data='...' 'http://...' | unicodeUnescape.py
    ...

'''
import sys

if __name__ == "__main__":
    for line in sys.stdin.readlines():
        print line.decode('unicode_escape')
