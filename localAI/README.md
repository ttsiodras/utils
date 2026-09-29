## Local LLM serving

### A. Serving small local models with llama.cpp

    ./launch.sh                  menu: guardrails / model / backend
                                 (Qwen3.5 9B Q4_K_M, Gemma4 12B QAT Q4_0 MTP, Vulkan)
    launch_common.sh             shared llama-server args: 127.0.0.1:8081
                                 --offline -ngl 99 --jinja --flash-attn on --mlock

`127.0.0.1:8081` is the default `../pi.isolated.sh --port` expects.

The launcher is meant to run in the end as a user whose egress drops (via
`../block_user_via_iptables.sh`). Only the very first launch needs internet,
to fetch the models from Hugging Face: run that one launch without the
blocking in place; then use it ever after.

### B. The much larger, LAN-hosted models

    benchmarks/                  recorded runs (DeepSeek-v4 0731, Qwen3.5-122B/397B,
                                 Gemma4-31b nvfp4+ray, Qwen3.6-27B-FP8, MiniMax-M2.7)
    launch.openwebui.sh          open-webui UI against the vLLM endpoint on that box

`launch.openwebui.sh` runs the upstream open-webui image under docker, so its
`OPENAI_API_BASE_URL` uses `172.17.0.1`, docker's bridge gateway to the host
(`host.containers.internal` under podman).

### C. Hosted-model sessions

    google-servers.txt           network allowlist for these sessions, fed to
                                 ../isolate.sh --servers

`../pi.google.sh`, `../pi.google_run.sh` and `../get_subs_tmux.sh` run `pi` through
`../pi.isolated.sh` (isolate.sh + firejail): `$HOME` read-only, only `$PWD`
writable, and the only host reachable off-box is the one listed in
`google-servers.txt`.

`--network=restricted_net` is used by two scripts, one per container CLI:
`../pi.containerized.vllm.sh` runs podman, which keeps its own network store, so
`podman network create restricted_net` is needed once; `../cclog.sh` runs docker,
whose `restricted_net` is created at boot by the dockerized-vim boot script
(`~/.vim/Dockerized/rc.local.vim`).

    pi.subagent/AGENTS.md        subagent prompt used by ../pi_parse_stream.py
    pi.extensions/               pi extensions (tokens-per-second)
