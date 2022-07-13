#!/bin/bash
percentile=$1
tmp="$(tempfile)"
total=$(sort -n | tee "$tmp" | wc -l)
# (n + 99) / 100 with integers is effectively ceil(n/100) with floats
count=$(((total * percentile + 99) / 100))
head -n $count "$tmp" | tail -n 1
rm "$tmp"
