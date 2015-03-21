#!/usr/bin/env python2
import sys
import json
import urllib2

inpFile = urllib2.urlopen(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
jsonData = json.loads(inpFile.read())
data = json.dumps(jsonData, sort_keys=True, indent=4,
                  separators=(',', ': '), ensure_ascii=False)
sys.stdout.write(data.encode('utf-8'))
