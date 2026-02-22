## Setup

- **Build images**: `make`
  - Builds both the GPT-OSS-120b and Qwen3-Next-80B-A3B docker images,
    for use with `claude.gpt-oss-120b.sh` and `claude.Qwen3-Next-80B-A3B-Instruct-GPTQ-Int4A16.sh`.

## Architecture

This is a Docker-based deployment system for driving local large language models (LLMs) with Claude Code, in a network-isolated setup.

The architecture consists of:

1. **Base Image (Dockerfile.base.vllm)**:
   - Uses Debian 12-slim as the base
   - Installs Node.js, npm, and busybox (for debugging - e.g. to confirm there's no network access inside the container).
   - Creates a non-root user with the same UID/GID as the user in the host system. When launched (e.g. `claude.gpt-oss-120b.sh`)
     the file/folder access permissions will match.
   - Installs Claude Code globally
   - Sets up environment variables needed for network-isolated operation.

2. **Model-Specific Images**:
   - GPT-OSS-120b (Dockerfile.gpt-oss-120b.vllm): Extends base image with GPT-OSS-120b configuration
   - Qwen3-Next-80B-A3B (Dockerfile.dazipe.Qwen3-Next-80B-A3B-Instruct-GPTQ-Int4A16.vllm): Extends base image with Qwen3-Next-80B-A3B configuration

3. **Configuration Files**:
   - settings.json.gpt-oss-120b: Configures GPT-OSS-120b model with endpoint at http://172.17.0.1:8000
   - settings.json.dazipe.Qwen3-Next-80B-A3B-Instruct-GPTQ-Int4A16: Configures Qwen3-Next-80B-A3B model with endpoint at http://172.17.0.1:8000
   - claude.json: Contains Claude Code onboarding state

The system uses the vLLM inference server x running at http://172.17.0.1:8000, with dummy API keys for local development.
Both models are configured to use the same endpoint - see `serve_gpt_oss_120b_vllm.sh` and `serve_Qwen3_Next_80B_A3B_Instruct_GPTQ_Int4A16_vllm.sh`
for details on how they are launched on a Strix Halo system.

The entire system is built to guarantee network isolation:

- The `vllm` server runs from a user that has no network access (see `../block_user_via_iptables.sh`). Only the first launch needs to have access,
  so it can download the model(s); in that first run, you need to comment out all the magic env vars prior to the `vllm` launch (in the `serve_...` scripts).
- Claude Code runs in a network isolated container: both ` claude.gpt-oss-120b.sh` and `claude.Qwen3-Next-80B-A3B-Instruct-GPTQ-Int4A16.sh`
  launch the containers in a restricted_net Docker network,
  [setup (for similar reasons) for isolating my Vim environment's language servers](https://github.com/ttsiodras/dotvim/blob/master/Dockerized/rc.local.vim).
- The network only allows visibility to the local (or in my case, SSH-fwded) vLLM endpoint; so there's no need to trust anything about
  the (closed-source) Claude Code and/or the npm jungle he lives in.
- Appropriate settings are used for both `vllm` and Claude Code to make them both happy enough to run without network access.
