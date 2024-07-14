#!/bin/bash
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
