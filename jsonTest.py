#!/usr/bin/env python
import sys
import json
import urllib2

jsonData = json.loads(urllib2.urlopen(sys.argv[1]).read())
sys.stdout.write(json.dumps(jsonData,
               sort_keys=True,
               indent=4,
               separators=(',', ': '), ensure_ascii=False))
