#!/bin/bash
DEVICE=${1:-/dev/nvme0n1}
fio                     \
    --name=readtest     \
    --filename=$DEVICE  \
    --direct=1          \
    --rw=read           \
    --bs=256k           \
    --iodepth=32        \
    --numjobs=$(nproc)  \
    --runtime=15        \
    --time_based        \
    --ioengine=io_uring \
    --group_reporting
