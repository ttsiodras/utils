#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

if [ $# -ne 2 ] ; then
    echo "Usage: $0 <filename.jsonl> <output.md>"
    exit 1
fi
docker images | grep cclog || {
    echo "[-] Run 'make cclog' from inside ${SCRIPT_DIR}/localAI to build the cclog image."
    exit 1
}
REALPATH="$(realpath "$1")"
docker run --rm \
  --network restricted_net \
  -v "$REALPATH":"$REALPATH":ro \
  cclog "$REALPATH" > "$2"
