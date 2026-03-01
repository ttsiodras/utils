#!/bin/bash
echo "[-] Remember to:"
echo "    socat TCP-LISTEN:8000,reuseaddr,fork,bind=172.17.0.1 TCP:localhost:8000"
docker run --network=restricted_net -w $PWD --rm -v $PWD:$PWD -it claude-gpt-oss-120b
