#!/usr/bin/env python2
'''
If you are able to generate (or filter - grep, sed, awk, etc) a list
of numbers in your stdout, then just pipe it to this utility, and
you will get nice, colored statistics in real-time, for every
sample that arrives:

    $ for i in {1..100} ; do echo $i ; sleep 1 ; done | statsLive.py

'''
import math

from sys import stdout

# Colored message ANSI constants
g_green = chr(27) + "[32m" if stdout.isatty() else ""
g_yellow = chr(27) + "[33m" if stdout.isatty() else ""
g_normal = chr(27) + "[0m" if stdout.isatty() else ""


def printStatsOfList(results, label='Statistics', summaryOnly=False):
    total = totalSq = n = 0
    for a in results:
        total += a
        totalSq += a*a
        n += 1
        varianceFull = (totalSq - total*total/n)/n
        if varianceFull < 0.:
            varianceFull = 0.
        if n > 1:
            variance = (totalSq - total*total/n)/(n-1)
            if variance < 0.:
                variance = 0.
        else:
            variance = 0.
        s = g_green + ("%6.2f" % (total/n)) + " +/- " + "%6.2f%%\n" + g_normal
        stdout.write(s % ((100*math.sqrt(variance)*n/total) if total > 0 else 0.),)
        stdout.flush()


def readListOfIntegersOrFloatsFromStdin():
    while True:
        try:
            a = float(raw_input())
            yield a
        except:
            break

if __name__ == "__main__":
    printStatsOfList(readListOfIntegersOrFloatsFromStdin())
