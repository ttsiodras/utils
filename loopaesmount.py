#!/usr/bin/env python
import os
import sys
import re
import socket
import string
import random


def mysystem(x):
    if 0 != os.system(x):
        print "Failed while executing:\n" + x
        exit(1)

if os.geteuid() != 0:
    print "Only as root"
    exit(1)

mysystem("modprobe dm_mod")
mysystem("modprobe aes-generic")

if '-c' in sys.argv:
    clearup = True
else:
    clearup = False
    if len(sys.argv) != 3:
        print "Usage:", sys.argv[0], "[-c] encryptedFileOrDev /path/to/mount"
        exit(1)

# Find all mounted cryptsetup stuff
mounted = {}
for line in os.popen("mount"):
    if re.match(r'^/dev/mapper/[a-z]+\s', line):
        mounted[line.split()[0].split('/')[3]] = 1

# Find all cryptsetup loop devices - and remove the unmounted ones
toRemove = {}
loopDevices = {}
for devname in os.listdir("/dev/mapper/"):
    if devname not in mounted and len(devname) == 38:
        mysystem("cryptsetup remove " + devname)
    else:
        for line in os.popen("cryptsetup status /dev/mapper/" + devname):
            if re.match(r'\s*device:\s*\S+$', line):
                loopDevices[line.split()[1]] = devname

# Filter loop devices - those that are no longer used, remove them
for loopinfo in os.popen("losetup -a"):
    loopdev = loopinfo.split(":")[0]
    if loopdev not in loopDevices:
        mysystem("losetup -d " + loopdev)

if clearup:
    exit(0)

# Use a fresh one for this mapping
newLoopDev = os.popen("losetup -f").readlines()[0].strip()

# Get pass
try:
    table = string.maketrans(
        'nopqrstuvwxyzabcdefghijklmNOPQRSTUVWXYZABCDEFGHIJKLM',
        'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')
    host = 'localhost'
    port = 50000
    size = 1024
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    data = s.recv(size)
    s.close()
    passwd = string.translate(data, table)
except:
    print "Gates are closed..."
    exit(1)

newCryptDev = ""
for i in xrange(0, 38):
    newCryptDev += random.choice("thequickbrownfoxjumpsoverthelazydog")
mysystem("losetup " + newLoopDev + " " + sys.argv[1])
mysystem(
    "echo " + passwd +
    "| cryptsetup -c aes-plain -h sha512 create " +
    newCryptDev + " " + newLoopDev)
mysystem("mount /dev/mapper/" + newCryptDev + " " + sys.argv[2])
