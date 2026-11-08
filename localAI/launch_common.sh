# launch_common.sh  (sourced by launch.sh, not executed directly)
#
# One place that decides how llama-server is started for the two local models,
# together with the measurements those decisions rest on.  See MEASUREMENTS at
# the bottom for the protocol and its error bars: most of what follows is a
# short-context number, and run-to-run drift on this laptop is large enough
# that only differences above ~25% should be trusted without a re-run.

# llama-server lives in this checkout's build/bin.  These launch scripts are
# hardlinked into the llama.cpp tree, so the root is derived from this file's
# own path rather than hardcoded: no username in the repo, and the checkout can
# move or be re-linked without editing anything.  LLAMA_SERVER overrides it.
LLAMA_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_SERVER="${LLAMA_SERVER:-$LLAMA_ROOT/build/bin/llama-server}"
if [ ! -x "$LLAMA_SERVER" ]; then
    echo "[!] $LLAMA_SERVER not found." >&2
    echo "    Run launch.sh from the llama.cpp checkout these scripts are" >&2
    echo "    hardlinked into, or set LLAMA_SERVER to the binary." >&2
    exit 1
fi

# Local port for llama-server.  Picked to stay clear of the ports other local
# services bind on this machine; pi's sandboxed side still dials 8080 inside
# its own netns, so point the bridge at this port explicitly:
#   ~/bin/pi.isolated.sh --port 8090
LLAMA_PORT=8090

# This build has GGML_SYCL=ON, and the SYCL backend enumerates its devices while
# the backend registry initialises, std::exit(1)-ing when the oneAPI runtime is
# missing (ggml-sycl.cpp:671) - even for a Vulkan-only run.  A login shell gets
# the env from the oneAPI setup; a plain ./launch.sh does not, and would die
# with "No device of requested type available", so set it up here if needed.
if [ -z "$OCL_ICD_FILENAMES" ] && [ -r /opt/intel/oneapi/setvars.sh ]; then
    . /opt/intel/oneapi/setvars.sh >/dev/null 2>&1
fi

# Flags shared by both models.
#   --offline     never contact the HF hub; the GGUFs must already be cached
#   --host        loopback only, nothing exposed on the LAN
#   --jinja       use the GGUF's own chat template.  Without it llama-server
#                 falls back to a generic template and pi's tool calls and
#                 reasoning preservation stop working
#   --parallel 1  one client, so the whole window belongs to a single slot and
#                 the slot/KV accounting stays simple (no second slot waiting
#                 on the same unified cache)
#   sampling      temp 0.6 / top-k 20 / top-p 0.95 / min-p 0.0 / presence 0.0 /
#                 repeat 1.0.  Both models are used here for coding, and both
#                 cards (Qwen3.5-9B and Qwen3.6-35B-A3B) give exactly this set
#                 for "thinking mode, precise coding tasks"; both cards'
#                 general-thinking recipe instead says temperature=1.0 with
#                 presence_penalty=1.5, and the base Qwen3.6 repo ships
#                 generation_config.json with temperature 1.0 / top_k 20 /
#                 top_p 0.95.  The coding numbers are taken on purpose:
#                 presence penalties cost code and tool-schema tokens more than
#                 they help, and pi is a coding agent.  Their agentic evals
#                 (SWE-Bench, Terminal-Bench) did run at temp=1.0, so 0.6 is a
#                 judgement call - the one flag worth A/B-ing if output ever
#                 looks too samey.
COMMON_ARGS="
  --offline
  --host 127.0.0.1
  --port $LLAMA_PORT
  --jinja
  --parallel 1
  --temp 0.6
  --top-k 20
  --top-p 0.95
  --min-p 0.0
  --presence-penalty 0.0
  --repeat-penalty 1.0
"

# Qwen3.5-9B, 5.46 GiB Q4_K_M plus an 880 MiB mmproj; 9.20 B, 33 blocks of
# which 9 hold full attention, KV 36 KiB/token.  Small enough that every layer
# fits the Vulkan heap, which is the only reason it is still interesting: its
# prompt processing is the fastest thing this laptop does (94 t/s), while its
# generation is the slowest (4.0-4.6 t/s) - see MEASUREMENTS.
#   --ctx-size 65536        KV stays in the Vulkan heap here (no -nkvo):
#                           36 KiB x 65536 = 2.25 GiB, and 5.46 + 2.25 plus
#                           compute buffers fits the 10.31 GiB Vulkan budget.
#                           pi auto-compacts at ctx - reserveTokens, so this is
#                           ~49k of usable window.
#   --image-min-tokens 1024 the mmproj is loaded, so vision is on; this caps
#                           what a single image may spend out of the window.
#   --n-gpu-layers 99       all layers fit, so ask for all of them.
#   --fit off               mandatory with an explicit -ngl: --fit aborts when
#                           the user has set n_gpu_layers (common/fit.cpp:550).
#   --flash-attn auto       measured within noise on this backend (fa off / on
#                           / auto all landed at 69-94 t/s pp and ~3.9-4.0 tg,
#                           the spread being run order), so let llama.cpp probe
#                           for support rather than forcing it.
# Sampling is not repeated here: it is identical for both models, see
# COMMON_ARGS above.
QWEN_ARGS="
  --hf-repo unsloth/Qwen3.5-9B-MTP-GGUF:Q4_K_M
  --ctx-size 65536
  --image-min-tokens 1024
  --n-gpu-layers 99
  --fit off
  --flash-attn auto
"

# Qwen3.6-35B-A3B, 10.85 GiB Q3_K_S; 34.66 B total but only ~3 B active per
# token, 40 blocks (30 SSM + 10 full attention), KV 20 KiB/token.  The active
# fraction is what makes it work here: ~0.95 GiB of weights read per token
# against ~5.5 GiB for the 9B, so it generates faster than the smaller model
# despite being twice the size on disk.
#   --ctx-size 32768        KV is 20 KiB/token, i.e. 640 MiB, and it is
#                           allocated outside the Vulkan heap (see below).
#                           Three reasons to stop at 32k rather than go deeper:
#                           pi auto-compacts at ctx - 16384, so this is already
#                           ~16k of usable window, and tg falls with depth (4.78
#                           t/s at ~13.4k on the Vulkan path, while the CPU path
#                           only loses ~1% going from e.g. 512 to 2048. DRAM is
#                           shared with the rest of the machine - 10.85 GiB of
#                           weights + 640 MiB of KV + compute buffers is ~12 GiB
#                           of the 15.3 GiB, so 64k would take another 640 MiB
#                           out of the ~3 GiB left for the OS and everything
#                           else.  A bigger window is possible (the KV is not in
#                           the Vulkan heap, so the Vulkan heap does not forbid
#                           it); it is just not free.
#   --no-kv-offload         at 32k the KV does not fit the Vulkan heap beside
#                           the weights (measured, see MEASUREMENTS), so those
#                           tensors are allocated from ordinary pageable memory
#                           instead - same DRAM, different arena, and it is the
#                           Vulkan heap's fixed size that is the binding limit,
#                           not free RAM.  llama.cpp then runs the 10 attention
#                           layers on the CPU (src/llama-graph.cpp:3168).  This
#                           costs ~15-25% of tg versus keeping KV in the Vulkan
#                           heap; that is the price of a 32k window here.
#   --no-mmproj             drops the 861 MiB vision projector: text-only use,
#                           and those 861 MiB of the Vulkan heap are then
#                           available to weights and compute buffers.  Not
#                           measured in isolation - the gain is Vulkan-heap
#                           headroom, not a specific t/s figure. If you need
#                           image reading abilities, use the 9B.
#   offload policy          backend-specific, see qwen36_device_args().
# Sampling is not repeated here: it is identical for both models, see
# COMMON_ARGS above.
QWEN36_ARGS="
  --hf-repo byteshape/Qwen3.6-35B-A3B-GGUF:Qwen3.6-35B-A3B-Q3_K_S-2.69bpw
  --ctx-size 32768
  --no-kv-offload
  --no-mmproj
"

# Device policy for the 35B, one line per backend.  Numbers in MEASUREMENTS.
#   Vulkan / SyCL  ngl 'auto' + --fit on (both defaults): the weights do not
#                  fit the 11.46 GiB Vulkan heap whole (that heap, not RAM, is
#                  the limit), and an explicit -ngl would make --fit abort, so
#                  let fit pick the split from free device memory at load time.
#                  --flash-attn auto rather than on, because forcing it skips
#                  the runtime probe (src/llama-context.cpp:714) and this hybrid
#                  arch is not a given on the iGPU.
#   CPU            -ngl 0 --no-op-offload --threads 8.  --no-op-offload is the
#                  global switch for llama.cpp's per-op offload
#                  (cparams.op_offload, ON by default), which otherwise lets a
#                  GPU backend take over host-resident ops whose batch is at
#                  least GGML_OP_OFFLOAD_MIN_BATCH (32, batch = ne[1] =
#                  tokens) - i.e. exactly prompt processing, which would drag
#                  the graph back onto the iGPU and need a compute buffer the
#                  Vulkan heap cannot always supply ("failed to allocate Vulkan0
#                  buffer of size 325980160").  --threads 8 because the CPU
#                  path is where generation is fastest and t=8 is its best
#                  point (t=12 collapses, see MEASUREMENTS).
qwen36_device_args() {
    case "$1" in
      1) echo "--device vulkan0 --n-gpu-layers auto --flash-attn auto" ;;
      2) echo "--device SYCL0 --n-gpu-layers auto --flash-attn auto" ;;
      3) echo "--n-gpu-layers 0 --no-op-offload --fit off --threads 8" ;;
      *) return 1 ;;
    esac
}

# ============================================================================
# MEASUREMENTS - read this before changing any flag above
# ============================================================================
# Taken 2026-11-08 with llama-bench from the same build as LLAMA_SERVER
# (llama.cpp b12205-a691b23458, GGML_SYCL=ON + Vulkan + CPU backends).
#
# Not measured here: the sampling parameters.  Those come from the model cards
# at huggingface.co/Qwen/Qwen3.6-35B-A3B and .../Qwen3.5-9B ("thinking mode for
# precise coding tasks"), cross-checked against the base repo's
# generation_config.json, and are recorded with COMMON_ARGS above.
#
# Hardware:
#   CPU   i5-1335U: 2 P-cores (+SMT) + 8 E-cores.  llama.cpp's default is
#         n_threads = 2 (it counts physical P-cores); that is what the server
#         prints at startup unless -t is given.
#   RAM   15.3 GiB total, NO swap, ~14 GiB MemAvailable when idle.  One pool:
#         the CPU and the iGPU read the same DRAM, there is no separate VRAM.
#   GPU   Intel UHD iGPU via Vulkan/ANV.  What is *not* the same pool is the
#         allocator: ANV exposes a fixed-size Vulkan heap of 11.46 GiB with a
#         10.31 GiB budget (vulkaninfo) carved out of that DRAM, so an
#         allocation can fail with ErrorOutOfDeviceMemory while ~14 GiB of DRAM
#         is free - the Vulkan heap size, not free memory, is the limit.
#         Tensors llama.cpp does not put in the Vulkan heap are ordinary
#         pageable allocations.  SYCL reaches the same iGPU through level_zero.
#
# Protocol:
#   command      llama-bench -p 512 -n 64 -r 1, one repetition (~+-10% noise)
#   warmup       ON (llama-bench default)
#   bench ctx    n_prompt + n_gen = 576 tokens unless -fitc/-d is passed, so
#                these are SHORT-CONTEXT numbers and say nothing about 8k-32k
#                depth
#   threads      -t 2 unless the row says otherwise
#   KV           -nkvo 1 where the row says so
#   layer split  fit picks it from *free* device memory at load time, so it
#                varies run to run: identical 35B flags measured pp 79.3 and
#                58.7
#
# Error bars - the important part.  Configs are benchmarked sequentially and
# this laptop drifts: the first config in an invocation runs at boost clocks,
# later ones do not, and the same nominal config measured pp 94.4 (first) and
# 69.1 (later) in one run of the 9B.  A thread sweep that looked like
# "pp 79 -> 60 -> 55 -> 52 at t=2/4/8/12" flattened to 55.9-57.1 when run in
# reverse order, so that was order, not threads.  Treat single-run differences
# under ~25% as unproven and re-run a sweep in both orders before acting on it.
# The robust results are the ones that reproduce across runs and directions:
#
# Qwen3.6-35B-A3B Q3_K_S  (10.85 GiB, 34.66 B total / ~3 B active, 40 blocks
#                          = 30 SSM + 10 full attention, KV 20 KiB/token)
#   CPU-only, ascending t (ngl0 -nopo)   CPU-only, reversed t
#     t2  38.9 pp / 10.65 tg               t12 29.9 pp /  5.70 tg
#     t4  26.4     / 10.95                 t8  32.7     / 10.94
#     t6  29.2     / 11.04                 t6  28.4     / 10.39
#     t8  33.9     / 11.79                 t4  25.1     / 10.39
#     t12 32.6     /  9.48                 t2  34.0     / 10.34
#     (standalone t8 run: 33.2 / 11.39)
#     -> tg peaks at t=8 (10.9-11.8) and collapses at t=12 (5.7-9.5); pp is
#        noisy but never better with more threads.  Hence --threads 8.
#
#   Vulkan, explicit -ngl so fit plays no part.  "KV in heap" below means the KV
#   tensors sit in the Vulkan heap; "-nkvo" means ordinary pageable memory.
#   Same DRAM either way - the difference is which allocator owns them and
#   therefore whether llama.cpp runs the attention ops on the device or the CPU:
#     ngl30 -nkvo  pp 76.6 / tg 5.58   |  KV in heap  pp 63.8 / tg 6.60
#     ngl40 -nkvo  pp 79.6 / tg 4.90   |  KV in heap  pp 61.4 / tg 6.53
#     -> keeping KV in the Vulkan heap is worth ~+20-30% tg (more at higher
#        ngl); the
#        pp gap in those rows is within drift, the tg gap is the solid part.
#        It is not available at ctx 32768, though: '-ngl 30 --fit off
#        -c 32768' dies with "failed to allocate Vulkan0 buffer of size
#        325980160" (compute buffers), so at 32k the 35B needs -nkvo on
#        Vulkan.
#     ngl30 reversed t (12,8,4,2): pp 55.9/56.9/56.7/57.1
#                                  tg 4.92/6.16/6.48/6.53
#     -> pp flat across thread counts; tg prefers the default t=2.  Do not
#        raise -t on a GPU path.
#     -ncmoe 20 / 40 (expert weights on CPU): pp 66.9 / 55.8, tg 4.49 / 4.36
#     -> pushing the experts to the CPU does not help tg, so the GPU's weak
#        generation is general batch-1 overhead, not MoE-specific.
#     ub256 pp 55.6 | ub512 pp 61.8 | ub1024 OOM
#       ("failed to allocate Vulkan0 buffer of size 1059069952"), so leave
#       ubatch at its 512 default.
#
#   KV cache quantization (same model; -ctk/-ctv):
#     CPU ngl0 -nopo t8, p512/n64:   f16/f16 33.9/11.79 | q8_0/q8_0 31.1/11.23
#                                    q8_0/f16 32.1/10.88
#     CPU ngl0 -nopo t8, p2048/n64:  f16/f16 30.9/11.24 | q8_0/q8_0 27.8/11.21
#     -> no tg gain at pi-relevant depth: CPU attention is only a few percent of
#        token time there, and dequantizing costs ~10% of pp.  What it does buy
#        is memory: KV halves, 640 MiB -> 320 MiB at 32k.
#     On Vulkan, q8_0 KV is what lets KV stay in the Vulkan heap at 32k at all,
#     and that is worth a lot for tg.  Measured at p2048/n64, t2:
#       nkvo, ngl40 (current 32k config)  pp 55.8 / tg 4.86
#       q8_0 KV in heap, ngl32            pp 50.6 / tg 6.34   (+30% tg)
#     The catch is that the split must be hardcoded: 'fit on' with q8_0 KV
#     and no explicit -ngl dies allocating a 251 MiB compute buffer, -ngl 34
#     dies at 289 MiB, and only -ngl 32 leaves room.  Quantized V also needs
#     Flash Attention (llama-context.cpp:623), so it is not a free option.
#     The gain comes from where the KV lives (attention on the GPU instead of
#     the per-layer CPU<->GPU hop), NOT from more layers on the GPU: with KV
#     in the heap, tg is flat at ngl 30 and ngl 40 (6.60 / 6.53).
#     Not adopted: the CPU path gains nothing from quantization, the Vulkan
#     variant stays below CPU even at its best (6.3 vs 11.2 t/s at the same
#     depth), and it is fragile.  Shrinking the window is not a lever here -
#     the backend choice is.
#
# Qwen3.5-9B Q4_K_M  (5.46 GiB, 9.20 B, 33 blocks with 9 full-attention
#                     layers, KV 36 KiB/token, 1 nextn/MTP layer)
#   Vulkan ngl99  pp 69-94 (position in the run matters, see error bars),
#                 tg 3.9-4.6
#   SyCL   ngl99  pp 59.8, tg 5.29
#   CPU    t8     pp 17.1, tg 5.30
#   --flash-attn off / on / auto: 94.4/69.1/69.1 pp and 4.02/3.95/3.94 tg in one
#     order, 78.6/69.1 pp in the reverse -> no resolvable effect; leave it auto.
#
# Speculative decoding with the 9B's MTP head (nextn_predict_layers=1), same
# request twice on Vulkan, ctx 8192, temp 0, 494-token prompt, 128 generated:
#   base                     pp 85.2 t/s | tg 4.34 t/s
#   --spec-type draft-mtp \
#   --spec-draft-n-max 3     pp 79.9 t/s | tg 4.28 t/s
#   draft acceptance 0.759 (88 accepted / 116 generated, mean len 3.26)
#   -> the draft head predicts well and buys nothing: verifying a 4-token
#      draft costs about what 4 separate tokens cost here.  6% pp loss for ~1%
#      tg is a net loss, so the flags stay off.  Not applicable to the 35B,
#      whose GGUF has no nextn/MTP tensors.
#
# Gemma4 12B QAT Q4_0 is not offered: dense 12B, so ~6.3 GiB of weights read per
# token (vs ~0.95 for the 35B-A3B, ~5.5 for the 9B).  Scaled from bytes/token
# rather than measured (its weights are not on disk), that is ~4.0 t/s tg on
# Vulkan / ~4.6 on CPU - the 9B's speed and 2.5x slower than the 35B, while
# being less capable than the 35B.  Worth adding only for its writing style or
# vision.
#
# What the numbers mean:
#   * Generation is bounded by bytes read per token, which is why the 35B-A3B
#     (~0.95 GiB) beats the 9B (~5.5 GiB) at tg and at CPU prompt processing.
#   * The 9B's only win is GPU prompt processing (94 vs 59-80 t/s), and that is
#     a first-turn cost: pi's prefix cache covers later turns.  Per turn (400
#     new prompt tokens + 500 generated): Vulkan-9B ~112 s vs CPU-35B ~56 s.
#   * GPU generation is limited by per-op cost, not bandwidth: even with KV in
#     the Vulkan heap the 35B reaches only 6.5 t/s, against 11.4 on the CPU.
#     llama.cpp
#     encodes the same judgement - a GPU backend only takes over an op whose
#     inputs are host resident when its batch is >= GGML_OP_OFFLOAD_MIN_BATCH
#     (32; ggml-backend.cpp:1386, batch = ne[1] = tokens).
#   * --fit off plus an explicit -ngl aborts (common/fit.cpp:550) unless the
#     model already fits; hence the 9B uses "-ngl 99 --fit off" and the 35B
#     keeps ngl 'auto' + fit on.
#
# Chosen defaults (see qwen36_device_args):
#   35B -> CPU t8 for pi work (tg-bound); Vulkan for one big fresh prompt;
#          SyCL is the best GPU choice for tg (5.3-7.0 vs 3.9-4.9 on Vulkan).
#   9B  -> Vulkan ngl99.  Its CPU path is +15% tg but 5.5x worse pp, a wash per
#          turn, so there is no CPU option for it in launch.sh.
# ============================================================================
