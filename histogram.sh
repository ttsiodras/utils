#!/bin/bash
SCRATCHPAD=/dev/shm/percentiles.txt.$$
SORTED="$(mktemp)"

function cleanup() {
    rm -f ${SCRATCHPAD} "${SORTED}"
}
trap cleanup EXIT

# Display nice histogram through Python, unless -n passed
if [ "$1" != "-n" ] ; then
    cat "$@" | tee ${SCRATCHPAD} | _histogram.py
else
    shift
    cat "$@" > ${SCRATCHPAD}
fi

# Display percentiles through Unix magic
TOTAL_LINES=$(sort -n <${SCRATCHPAD} | tee "${SORTED}" | wc -l)
if [ $TOTAL_LINES -eq 0 ] ; then 
    exit
fi
echo -e "\n[31mPercentiles:[0m"
for PCT in 97 95 90 75 50 25 ; do
	echo -ne "\t${PCT}% = "
	# (n + 99) / 100 with integers is effectively ceil(n/100) with floats
	COUNT=$(((TOTAL_LINES * PCT + 99) / 100))
	head -n $COUNT "${SORTED}" | tail -n 1
done
