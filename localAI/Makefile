all:
	docker build \
	  --build-arg UID=$$(id -u)     	\
	  --build-arg GID=$$(id -g)     	\
	  --build-arg USERNAME=$$(whoami)	\
	  -t claude-gpt-oss-120b -f Dockerfile.gpt-oss-120b.vllm .
