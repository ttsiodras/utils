#!/bin/bash
docker run --network=restricted_net -w $PWD --rm -v $PWD:$PWD -it claude-qwen3-next-80b-a3b-instruct-gptq-int4a16
