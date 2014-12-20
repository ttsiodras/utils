#!/home/ttsiod/.virtualenvs/flask/bin/python2
"""
A custom script (tailor-made to my machines) that uses
all the CPU cores of my machine to add up the lengths
of the movies passed to it in the command line.
"""
import os
import sys

from concurrent import futures


def getMovieLength(filename):
    if not os.path.isfile(os.path.realpath(filename)):
        return filename, 0.
    cmd = "mplayer -nosound -quiet -identify -frames 0 -vo null "
    cmd += "\"%s\" 2>/dev/null | grep LENGTH" % filename
    try:
        return filename, float(os.popen(cmd).readlines()[0].split('=')[1])
    except:
        return filename, 0.


def main():
    cmd = "cat /proc/cpuinfo  |grep ^processor | wc -l"
    totalCPUs = int(os.popen(cmd).readlines()[0])
    print "   Movie (sec)     Running Total"
    with futures.ProcessPoolExecutor(max_workers=totalCPUs) as executor:
        total = 0.
        for filename, movieLength in executor.map(
                getMovieLength, sys.argv[1:]):
            total += movieLength
            totalHours = int(total / 3600)
            totalMinutes = int(total / 60) - totalHours*60
            totalSeconds = int(total) - totalHours*3600 - totalMinutes*60
            print "%13.2f    %4d:%02d:%02d %s" % (
                movieLength,
                totalHours,
                totalMinutes,
                totalSeconds,
                filename)
    os.system("stty icanon echo")

if __name__ == "__main__":
    main()
