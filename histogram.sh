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

# # Display percentiles through Unix magic
# TOTAL_LINES=$(sort -n <${SCRATCHPAD} | tee "${SORTED}" | wc -l)
# if [ $TOTAL_LINES -eq 0 ] ; then 
#     exit
# fi

echo

(
echo -en "MIN\tMED\tAVG\tMAX\t"
PCTS="25 50 75 90 99 99.9 99.99 99.999"
CMD="datamash --format=%10.5f min 1 median 1 mean 1 max 1"

for PCT in $PCTS
do
	echo -en "${PCT}%\t"
        CMD="$CMD perc:$PCT 1"
done
echo
$CMD < ${SCRATCHPAD} | sed 's,\.00*\t,\t,g'
) | column -t
# 	# (n + 99) / 100 with integers is effectively ceil(n/100) with floats
# 	COUNT=$(((TOTAL_LINES * PCT + 99) / 100))
# 	head -n $COUNT "${SORTED}" | tail -n 1
# done
