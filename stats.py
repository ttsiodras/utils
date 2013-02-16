#!/usr/bin/env python
import math
import sys
green = chr(27)+"[32m" if sys.stdout.isatty() else ""
normal = chr(27)+"[0m" if sys.stdout.isatty() else ""
total = totalSq = n = 0
allOfThem = []
while True:
    try:
        a = float(raw_input())
    except:
        break
    total += a
    totalSq += a*a
    n += 1
    allOfThem.append(a)
if n in [0, 1]:
    print "%s data point read... aborting." % (
        "only one" if n == 1 else "no")
    sys.exit(1)

varianceFull = (totalSq - total*total/n)/n
variance = (totalSq - total*total/n)/(n-1)
srted = sorted(allOfThem)
measurements = [
    ("Elements", n),
    ("Average value", total/n),
    ("Std deviation", math.sqrt(varianceFull)),
    ("Sample stddev", math.sqrt(variance)),
    ("Median", srted[len(allOfThem)/2]),
    ("Min", srted[0]),
    ("Max", srted[-1]),
    (green+"Overall", (str(total/n)+" +/- "+"%2.1f%%"+normal) %
        (100*math.sqrt(variance)*n/total))
]
for label, value in measurements:
    print "%*s:" % (15, label), value
