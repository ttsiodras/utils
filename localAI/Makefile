all:
	# Build the GPT‑OSS‑120b image
	docker build \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  --build-arg USERNAME=$$(whoami) \
	  --build-arg SETTINGS_SRC=settings.json.gpt-oss-120b \
	  -t claude-gpt-oss-120b -f Dockerfile.base.vllm .
	# Build the Qwen3‑Next‑80B‑A3B image
	docker build \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  --build-arg USERNAME=$$(whoami) \
	  --build-arg SETTINGS_SRC=settings.json.dazipe.Qwen3-Next-80B-A3B-Instruct-GPTQ-Int4A16 \
	  -t claude-qwen3-next-80b-a3b-instruct-gptq-int4a16 -f Dockerfile.base.vllm .
