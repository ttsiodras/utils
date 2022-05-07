#!/bin/bash
cd /root/bin.local/ || exit 1
python3 ../bin/lost_my_space.py "$@" | tee /dev/shm/lost
sort -n /dev/shm/lost > /dev/shm/a
mv /dev/shm/a /dev/shm/lost 
exclude.sh /dev/shm/lost
rm /dev/shm/lost
