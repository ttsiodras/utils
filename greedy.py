#!/usr/bin/env python
"""
Dynamic programming in practise.
Read my blog post at:
    https://www.thanassis.space/fillupDVD.html
"""
import sys

g_maxSize=int(sys.argv[1])


def main():
    data = []
    for key in sys.stdin.readlines():
        try:
            key = int(key)
            data.append(key)
        except:
            print("%s is not numeric" % key)
            continue

    print("Total of ", len(data), "items")
    print(data)
    dynamic = []

    # Build our table of N x M, with pairs of (0,0) as elements
    for i in range(0, g_maxSize+1):
        dynamic.append([])
        for j in range(0, len(data)+2):
            # optimal result: 0, last step to get there: 0
            dynamic[i].append([0, 0])
    # all files 1..j
    for j in range(1, len(data)+1):
        # all sizes up to g_maxSize
        for w in range(1, g_maxSize+1):
            if data[j-1] > w:
                # file j won't fit in container,
                # so copy best from j-1 files
                dynamic[w][j][0]=dynamic[w][j-1][0]
                dynamic[w][j][1]=dynamic[w][j-1][1]
            else:
                # file j fits in this container,
                # but does it improve things?
                if dynamic[w][j-1][0] >= \
                      dynamic[w-data[j-1]][j-1][0] + data[j-1]:
                    # No, it doesn't.
                    dynamic[w][j][0] = dynamic[w][j-1][0]
                    dynamic[w][j][1] = 0     # dummy last step
                else:
                    # Well it does! Update the optimal result
                    # and the last step
                    dynamic[w][j][0] = \
                        dynamic[w-data[j-1]][j-1][0] + data[j-1]
                    dynamic[w][j][1] = data[j-1]

    print("Attainable: ", dynamic[g_maxSize][len(data)][0])
    total = 0
    line = g_maxSize
    pieces = len(data)
    while total < dynamic[g_maxSize][len(data)][0]:
        total += dynamic[line][pieces][1]
        print("+", dynamic[line][pieces][1], "=", total)
        line = line-dynamic[line][pieces][1]
        pieces-=1
        if pieces == 0:
            break

if __name__ == "__main__":
    main()
