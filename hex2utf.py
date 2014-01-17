#!/usr/bin/env python2
'''
This is a quick hack to dump error logs written in e.g. PHP error logs
(they use the \xDE\xAD\xBE\xEF encoding - which is native in Python,
 so a simple exec works :-)
'''

import sys
f = open(sys.argv[1]) if len(sys.argv)>1 else sys.stdin
for line in f.readlines():
    exec("hack='" + line.strip() + "'")
    sys.stdout.write(hack)
