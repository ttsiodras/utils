#!/usr/bin/env python3
"""
Observe mean and stddev of input data coming over stdin.

$ for i in {1..10} ; do echo $i ; sleep 1 ; done | \
        ./incremental_stats.py 5

The optional argument indicates number of fractional digits.

"""
import sys
import math

# From: https://en.wikipedia.org/wiki/\
#       Algorithms_for_calculating_variance#Welford's_online_algorithm


# For a new value newValue, compute the new count, new mean, the new M2.
# mean accumulates the mean of the entire dataset
# M2 aggregates the squared distance from the mean
# count aggregates the number of samples seen so far
def update(existingAggregate, newValue):
    count, mean, M2 = existingAggregate
    count += 1
    delta = newValue - mean
    mean += delta / count
    delta2 = newValue - mean
    M2 += delta * delta2
    return count, mean, M2


# Retrieve the mean, variance and sample variance from an aggregate
def finalize(existingAggregate):
    count, old_mean, M2 = existingAggregate
    if count < 2:
        return float("nan")
    mean, variance = old_mean, M2 / count
    return mean, variance


def main():
    if '-h' in sys.argv:
        print("Usage:", sys.argv[0], '<digits>')
        sys.exit(1)
    digits = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    clr_to_eol = "\033[K\r"
    state = (0, 0, 0)
    for idx, line in enumerate(sys.stdin):
        value = float(line)
        state = update(state, value)
        if idx > 1:
            mean, variance = finalize(state)
            print("Mean: %.*f  StdDev: %.*f" % (
                digits, mean, digits, math.sqrt(variance)),
                end=clr_to_eol, flush=True)


if __name__ == "__main__":
    main()
