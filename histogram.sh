#!/bin/bash
cat "$@" | tee /dev/shm/percentiles.txt | _histogram.py
echo -e "\n[31mPercentiles:[0m"
for i in 97 95 90 75 50 25 ; do
    echo -ne "\t${i}% = "
    cat /dev/shm/percentiles.txt | percentile.sh $i
done
rm -f /dev/shm/percentiles.txt
