#!/bin/bash
SORTED="$(mktemp)"
function cleanup() {
    rm -f "${SORTED}"
}
trap cleanup EXIT

TOTAL_LINES=$(sort -n | tee "${SORTED}" | wc -l)
for PCT in 97 95 90 75 50 25 ; do
	echo -ne "\t${PCT}% = "
	# (n + 99) / 100 with integers is effectively ceil(n/100) with floats
	COUNT=$(((TOTAL_LINES * PCT + 99) / 100))
	head -n $COUNT "${SORTED}" | tail -n 1
done
rm "${SORTED}"
