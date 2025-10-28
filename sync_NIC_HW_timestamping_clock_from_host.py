#!/usr/bin/env python3
"""
tcpdump will not report proper HW timestamping unless this is used,
to synchronize the NIC HW clock with the host clock. You can then
get proper timestamps in both TX/RX directions:

  tcpdump                              \
    -B $((1*1048576))                  \
    -i enp1s0f1np1                     \
    -w /dev/shm/why.pcap               \
    --time-stamp-type=adapter_unsynced \
    --nano --immediate-mode            \
      'not port 5201'

Potential systemd service:

    # /etc/systemd/system/phc2sys@.service
    [Unit]
    Description=phc2sys: sync %I to /dev/ptp6
    After=network-online.target
    Wants=network-online.target
    
    [Service]
    Type=simple
    ExecStart=/usr/sbin/phc2sys -m -s CLOCK_REALTIME -c /dev/ptp6 -O 0
    Restart=always
    RestartSec=2
    
    [Install]
    WantedBy=multi-user.target

"""
import os
import sys

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} interface_name")
        sys.exit(1)

    clock = ""
    pattern = "PTP Hardware Clock"
    for line in os.popen(f"sudo ethtool -T {sys.argv[1]}").readlines():
        if line.startswith(pattern):
            clock = "/dev/ptp" + line.split()[-1].strip()
            break
    else:
        print(f'[x] Failed to find "{pattern}"')
        sys.exit(1)

    if not os.path.exists(clock):
        print(f'[x] Failed to find {clock}')
        sys.exit(1)
    cmd = f"sudo phc2sys -s CLOCK_REALTIME -c {clock} -O 0 -m"
    print(f"[-] Launching: {cmd}")
    os.system(cmd)


if __name__ == "__main__":
    main()
