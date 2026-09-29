#!/bin/bash
# ---------------------------------------------------------------------------
# Run Genymotion with no internet, but with a working localhost.
#
# This creates a private network namespace, brings up only its loopback, gives
# it no default route, and then runs a shell inside it.  Start genymotion from
# that shell: the emulator cannot reach the internet, while everything that
# talks over 127.0.0.1 (adbd) keeps working.
#
# Why a namespace, and not simply "no network":
#
#   Genymotion's Player talks to the guest's adbd over TCP on the loopback
#   interface only.  Its own log lines look like:
#
#       [Adb][connect]      "127.0.0.1:6555"
#       [Adb][isConnected]  "127.0.0.1:6555" : "device"
#       /opt/genymotion/tools/adb -s "127.0.0.1:6555" shell getprop dev.bootcomplete
#
#   (6555 is the host-side port Genymotion forwards to the guest's adb port
#   5555.)  A sandbox with no usable loopback (firejail --net=none, for
#   instance) therefore does not work at all: the Player never sees the device,
#   and the VM looks dead.  A network namespace gives the combination that is
#   actually needed: lo is up and owns 127.0.0.1/8, so localhost IPC works, and
#   there is no default route, so there is no internet.
#
#   Two consequences of that loopback being private:
#
#     * 127.0.0.1 in here is NOT the host's 127.0.0.1.  Nothing that was
#       already listening on the host's localhost interface can be reached from
#       in here, or the other way round. So genymotion and adb both have to be
#       started inside this shell.
#
#     * DISPLAY must keep its "empty host" form, ':0.0' (or ':0', which is the
#       same thing).  In DISPLAY=[host]:display.screen the host part selects the
#       *transport*, not just an address: an empty host makes the X client use
#       the local AF_UNIX socket /tmp/.X11-unix/X0, and a network namespace does
#       not isolate the filesystem, so that socket still reaches the real X
#       server. 
#
#   Genymotion >= 3.x runs its own QEMU (/opt/genymotion/qemu, virtio-net card,
#   userspace networking), so the guest's NIC lives inside the VM process.  That
#   process inherits this namespace and, deliberately, loses internet because of
#   it; no host tap or bridge device is involved.
# ---------------------------------------------------------------------------
set -

NAMESPACE="isolated"

# Create network namespace
sudo ip netns add $NAMESPACE

# Create veth pair
sudo ip link add veth0 type veth peer name veth1

# Assign veth1 to the new namespace
sudo ip link set veth1 netns $NAMESPACE

# Configure interfaces
sudo ip addr add 127.0.0.1/8 dev veth0
sudo ip link set veth0 up

sudo ip netns exec $NAMESPACE ip addr add 127.0.0.1/8 dev lo
sudo ip netns exec $NAMESPACE ip link set lo up
sudo ip netns exec $NAMESPACE ip link set veth1 up
sudo ip netns exec $NAMESPACE ip route add 127.0.0.0/8 dev lo

# Run a command in the new namespace
# sudo ip netns exec $NAMESPACE bash -c "su - ttsiod -c 'export DISPLAY=:0.0 ; /bin/bash'"
echo "Remember: you need to set DISPLAY=:0.0 before launching genymotion"
sudo ip netns exec $NAMESPACE bash

# Cleanup
sudo ip link del veth0
sudo ip netns del $NAMESPACE
