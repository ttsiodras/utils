#!/bin/bash
if [ $# -ne 1 ] ; then
    echo Usage: $0 user
    exit 1
fi
/usr/bin/iptables -D OUTPUT -s 172.17.0.1/16 -d 172.17.0.1/16 -m owner --uid-owner $1 -j ACCEPT 
/usr/bin/iptables -D OUTPUT -s 127.0.0.1 -d 127.0.0.1 -m owner --uid-owner $1 -j ACCEPT 
/usr/bin/iptables -D OUTPUT -m owner --uid-owner $1 -j DROP
