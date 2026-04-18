all:
	docker build \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  --build-arg USERNAME=$$(whoami) \
	  -t adk \
	  -f Dockerfile.base.adk \
	  .

pi:
	docker build \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  --build-arg USERNAME=$$(whoami) \
	  -t pi  \
	  -f Dockerfile.base.pi \
	  .

pi-google:
	docker build \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  --build-arg USERNAME=$$(whoami) \
	  -t pi-goolge  \
	  -f Dockerfile.base.googleai.pi \
	  .

big:
	# Build the GPT-OSS-120b claude code image
	docker build \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  --build-arg USERNAME=$$(whoami) \
	  --build-arg SETTINGS_SRC=settings.json.gpt-oss-120b \
	  -t claude-gpt-oss-120b \
	  -f Dockerfile.base.vllm \
	  .
	# Build the GPT-OSS-120b codex image
	docker build \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  --build-arg USERNAME=$$(whoami) \
	  -t codex-gpt-oss-120b \
	  -f Dockerfile.base.codex \
	  .
	# Build the Qwen3-Next-80B-A3B image
	docker build \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  --build-arg USERNAME=$$(whoami) \
	  --build-arg SETTINGS_SRC=settings.json.dazipe.Qwen3-Next-80B-A3B-Instruct-GPTQ-Int4A16 \
	  -t claude-qwen3-next-80b-a3b-instruct-gptq-int4a16 \
	  -f Dockerfile.base.vllm \
	  .
qwen:
	# Build the Qwen3.5-122B-A10B
	docker build \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  --build-arg USERNAME=$$(whoami) \
	  -t qwen3.5-122b-a10b \
	  -f Dockerfile.base.qwen \
	  .
