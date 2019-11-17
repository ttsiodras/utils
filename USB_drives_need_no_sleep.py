#!/usr/bin/env python3
"""
I've set up my AtomicPI (https://www.thanassis.space/atomicpi.html) as a ZFS
server, with two external USB 2TB drives in a mirror configuration:

    # zpool status
     ...
    config:

            NAME             STATE     READ WRITE CKSUM
            tank             ONLINE       0     0     0
              mirror-0       ONLINE       0     0     0
                nova         ONLINE       0     0     0
                solarsystem  ONLINE       0     0     0

    errors: No known data errors

Even though the AtomicPI is not an ECC-equipped machine, this setup is by far
the best configuration - error-tolerance-wise - than anything else at that
price point.

The USB drives go to sleep when unused - and I don't like that. I only power up
the machine remotely (https://www.thanassis.space/remotepower.html) when
I want to do some work that depends on them being always on.

I first tried some things that have worked elsewhere...

    hdparm -S 0 -B 255 /dev/...
    sdparm --clear=STANDBY /dev/... -S

...but they didn't work here; at least one drive still went to sleep after
a while.

So, I used this script - together with a simple supervisor configuration:

    # cat /etc/supervisor/conf.d/usbdrives.conf
    [program:usbdrives]
    command=/root/bin.local/USB.drives.never.sleep.py
    autostart=true
    autorestart=true
    stderr_logfile=/var/log/USB.drives.stderr.log
    stdout_logfile=/var/log/USB.drives.stdout.log

...which works just fine; reading a few (CNT_SECTORS) random sectors
from all the /dev/sd* devices every 4 minutes.
"""
import os
import sys
import time
import random
import logging
import subprocess


CNT_SECTORS = 10


def panic(msg):
    """
    Log message and abort.
    """
    logging.error(msg)
    sys.exit(1)


def main():
    """
    Run forever, keeping drives awake.
    """
    # logging.basicConfig(level=logging.INFO)
    cmd = "lsblk | grep ^sd | awk '{print $1}'"
    get_devices_cmd = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    devices = [d.strip().decode('utf-8')
               for d in get_devices_cmd.stdout.readlines()]
    get_devices_cmd.wait()
    while True:
        for dev in devices:
            logging.info("[-] Waking up %s", dev)
            cmd = "blockdev --getsz /dev/" + dev
            try:
                block_size_in_sectors = int(os.popen(cmd).read().strip())
            except ValueError as ex:
                panic("[x] Failed to find size in sectors... Aborting.\n"
                      "Error string: " + block_size_in_sectors + " " + str(ex))
            logging.info("[-] Accessing %d sectors inside %s",
                         CNT_SECTORS, dev)
            # print("[-] Sectors ")
            for _ in range(CNT_SECTORS):
                sector_offset = random.randint(0, block_size_in_sectors)
                # print(str(sector_offset) + ", ", end='')
                cmd = "dd if=/dev/" + dev + " of=/dev/null bs=512 count=1"
                cmd += " skip=" + str(sector_offset) + " status=none"
                res = subprocess.run(cmd, shell=True, capture_output=True)
                if res.returncode != 0:
                    panic("[x] Failed!"
                          ": cmd was: '" + cmd + "'"
                          ", stdout was: '" + res.stdout.decode('utf-8') + "'"
                          ", stderr was: '" + res.stderr.decode('utf-8') + "'")
            logging.info('[-] Accesses completed, %s wide awake!', dev)

        logging.info("[-] Sleeping for 4 minutes...")
        time.sleep(240)


if __name__ == "__main__":
    main()
