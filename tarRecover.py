#!/usr/bin/env python
'''
I wrote this before I discovered...

    cpio -ivd -H tar ...

...to recover files from corrupt .tar balls. Oh well.
'''

import os
import re
import sys
import getopt
import string


def usage():
    print '''\
My quick and dirty solution to extract files from a corrupted .tar archive.
Usage: {{appName}} <options>

where mandatory options are:

    -i, --input <inputToReadFrom>   Where to read TAR data from
                                    (use /dev/stdin to read from stdin)

and one of:

    -l, --list                      Don't extract - just list the files
    -x, --extract                   Extract the files into <folderName>

and optional ones:

    -o, --outputFolder <folderName> Where to extract contained files
                                    (default: current folder)
    -h, --help                      This help message

For issues/suggestions, contact Thanassis Tsiodras (ttsiodras@gmail.com)
'''.format(appName=os.path.basename(sys.argv[0]))
    sys.exit(1)


def panic(x):
    sys.stderr.write(x)
    sys.exit(1)


def main():
    ustar = "ustar  " + chr(0)
    validFilenameChars = "-_,/." + string.digits + string.letters

    try:
        args = sys.argv[1:]
        optlist, args = getopt.gnu_getopt(
            args, "hlxi:o:",
            ['help', 'list', 'extract', 'input=', 'outputFolder='])
    except:
        usage()

    inputSource = None
    listOnly = None
    outputFolder = "."
    for opt, arg in optlist:
        if opt in ("-h", "--help"):
            usage()
        elif opt in ("-l", "--list"):
            if listOnly is not None:
                panic("\nOnly one of -l, -x can be used\n")
            listOnly = True
        elif opt in ("-x", "--extract"):
            if listOnly is not None:
                panic("\nOnly one of -l, -x can be used\n")
            listOnly = False
        elif opt in ("-i", "--input"):
            inputSource = arg
            if not os.path.exists(inputSource):
                print "\nInvalid input source:", inputSource, "\n"
                usage()
        elif opt in ("-o", "--outputFolder"):
            outputFolder = arg
            if not os.path.isdir(outputFolder):
                print "\nCan't find folder:", outputFolder, "\n"
                usage()
        else:
            usage()

    if listOnly is None:
        print "\nYou must use either -l or -x!\n"
        usage()

    if args:
        usage()

    try:
        f = open(inputSource, 'rb')
    except:
        panic("Failed to open '%s' for reading - aborting..." % inputSource)
    fo = None
    foSize = None
    writtenSoFar = 0
    oldData = ''
    preReadSector = False
    while True:
        if not preReadSector:
            sectorData = f.read(512)
            if not sectorData:
                break
        else:
            preReadSector = False
        sectorLength = len(sectorData)
        idx = sectorData.find(ustar)
        if idx != -1:
            ustarIdx = idx
            headerIdx = idx - 257
            if headerIdx < 0:
                sectorData = oldData + sectorData
                sectorLength += len(oldData)
                idx += len(oldData)
                ustarIdx = idx
                headerIdx = idx - 257
                assert headerIdx >= 0
            if ustarIdx + 255 > sectorLength:
                sectorData += f.read(512)
                sectorLength = len(sectorData)
            if sectorData[headerIdx+107] != chr(0) or \
                    sectorData[headerIdx+115] != chr(0) or \
                    sectorData[headerIdx+123] != chr(0):
                continue

            # Extract filename from header
            idx, filenameChars = headerIdx, []
            while sectorData[idx] in validFilenameChars:
                filenameChars.append(sectorData[idx])
                idx += 1
                if idx >= sectorLength:
                    panic("Unexpected - need to lookahead more? Contact me...")
            filename = ''.join(filenameChars)

            # Extract file size from header
            try:
                foSize = int(sectorData[ustarIdx-133:ustarIdx-133+11], 8)
            except:
                continue
            if foSize == 0:
                print "Ignoring link/folder", filename, "(size: 0 bytes)"
                sectorData = sectorData[ustarIdx+1:]
                preReadSector = True
                continue

            # Report or extract (depending on whether --listOnly (-l) was used)
            print '%s file:' % 'Detected' if listOnly else "Extracting", \
                filename, ",", foSize, "bytes long."
            sys.stdout.flush()
            if not listOnly:
                filename = outputFolder + '/' + filename
                if '/' in filename:
                    os.system("mkdir -p " + re.sub(r'/[^/]*$', '', filename))
                fo = open(filename, 'wb')
                lenToWrite = min(foSize, sectorLength - (ustarIdx+255))
                fo.write(
                    sectorData[ustarIdx+255:ustarIdx+255+lenToWrite])
                writtenSoFar = lenToWrite
                while writtenSoFar < foSize:
                    buf = f.read(min(65536, foSize-writtenSoFar))
                    writtenSoFar += len(buf)
                    fo.write(buf)
                fo.close()
        else:
            oldData = sectorData[-512:]


if __name__ == "__main__":
    main()
