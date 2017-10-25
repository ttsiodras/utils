#!/usr/bin/env python2
import csv
import sys

if len(sys.argv)<2:
   print "Usage:", sys.argv[0], "file1 <file2> ..."
   sys.exit(1)
print "<html><head></head><body><table>"
for f in sys.argv[1:]:
   for line in csv.reader(open(f,'r')):
      print "<tr>"
      for elem in line:
	 print "<td>", str(elem), "</td>"
      print "</tr>"
print "</table></body></html>"

