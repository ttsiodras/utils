#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
This utility reads output from scripts that do 
something like this:

    while true 
    do
        somework 
        echo $? >> log 
        date >> log
    done

...and shows the time it takes for each run.
I am in a Greek locale, so I had to set it up first
to read lines like this:

    0
    Πεμ 14 Μάρ 2013 04:06:47 μμ EET
    0
    Πεμ 14 Μάρ 2013 04:13:05 μμ EET
    0
    Πεμ 14 Μάρ 2013 04:19:24 μμ EET
    0
    Πεμ 14 Μάρ 2013 04:25:42 μμ EET

'''

import sys
import locale
import time

locale.setlocale(locale.LC_ALL, 'el_GR.UTF-8')
last = None
for l in open(sys.argv[1]).readlines():
    if u'EET' in l.strip().decode('utf-8'):
        tup = time.strptime(l.strip(), '%a %d %b %Y %I:%M:%S %p %Z')
        new = time.mktime(tup)
        if last:
            print new - last # , '#', new, '#', l,
        last = new

