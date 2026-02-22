all:
	docker build \
	  --build-arg UID=$$(id -u)     	\
	  --build-arg GID=$$(id -g)     	\
	  --build-arg USERNAME=$$(whoami)	\
	  -t claude-gpt-oss-120b -f Dockerfile.gpt-oss-120b.vllm .
	docker build \
	  --build-arg UID=$$(id -u)     	\
	  --build-arg GID=$$(id -g)     	\
	  --build-arg USERNAME=$$(whoami)	\
	  -t claude-qwen3-next-80b-a3b-instruct-gptq-int4a16 -f Dockerfile.dazipe.Qwen3-Next-80B-A3B-Instruct-GPTQ-Int4A16.vllm .
