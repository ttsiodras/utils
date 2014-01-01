#!/bin/bash

CPUS=$(grep -c proc /proc/cpuinfo)

function pwait() {
    while [ $(jobs -p | wc -l) -ge $1 ]; do
        echo Maximum CPUs reached... waiting...
        sleep 1
    done
}

for whatever in {1..10} ; do
    echo Spawning another 5 second wait...
    sleep 5 &
    pwait $CPUS
done

echo Waiting for all to finish...
wait
echo All done.
