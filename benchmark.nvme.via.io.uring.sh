#!/bin/bash
DEVICE=${1:-/dev/nvme0n1}
fio                      \
    --name=readtest      \
    --filename="$DEVICE" \
    --direct=1           \
    --rw=read            \
    --bs=1M              \
    --iodepth=8          \
    --numjobs=1          \
    --runtime=10         \
    --time_based         \
    --ioengine=io_uring  \
    --group_reporting
