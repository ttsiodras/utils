#!/bin/bash
SCRATCHPAD=/dev/shm/percentiles.txt.$$
SORTED="$(mktemp)"

function cleanup() {
    rm -f ${SCRATCHPAD} "${SORTED}"
}
trap cleanup EXIT

NO_HISTO=0
NO_OUTLIERS=0

while [[ "$1" =~ ^- ]]; do
    case "$1" in
        -n)
            NO_HISTO=1
            shift
            ;;
        -r)
            NO_OUTLIERS=1
            echo "Ignoring outliers..." >&2
            shift
            ;;
        --) # stop parsing flags
            shift
            break
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

if [[ $NO_OUTLIERS -eq 1 ]]; then
    cat "$@" | histogram.py -o - - > "${SCRATCHPAD}"
else
    cat "$@" > "${SCRATCHPAD}"
fi

if [[ $NO_HISTO -ne 1 ]]; then
    cat "${SCRATCHPAD}" | _histogram.py
fi

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
    $CMD < ${SCRATCHPAD} | sed -E 's/(\.[0-9]*[1-9])0+([[:space:]]|$)/\1\2/g;s/\.0+([[:space:]]|$)/\1/g;'
) | column -t
