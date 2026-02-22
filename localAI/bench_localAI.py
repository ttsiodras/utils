import asyncio
import sys
import logging
import time
import statistics
import argparse
import json

from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

# ---- CONFIG ----
BASE_URL = "http://172.17.0.1:8000/v1"
API_KEY = "EMPTY"  # vLLM doesn't require a real key

DEFAULT_CONCURRENCY = 1
DEFAULT_REQUESTS_PER_WORKER = 4
DEFAULT_MAX_TOKENS = 512
PROMPT = "Write a detailed technical explanation of how KV caching works in transformer inference."

# ----------------

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
)

async def get_default_model():
    """Return the first model ID reported by the vLLM server.
    If the server returns no models, abort with a clear error message."""
    try:
        models = await client.models.list()
        if not models.data:
            logging.error("No models available on the vLLM server.")
            sys.exit(1)
        first_model = models.data[0].id
        logging.info(f"Selected default model '{first_model}' from server list.")
        return first_model
    except Exception as e:
        logging.error(f"Failed to retrieve model list: {e}")
        sys.exit(1)

async def single_request(model, max_tokens):
    """Execute a single request and return performance metrics."""
    start_time = time.perf_counter()
    first_token_time = None
    total_tokens = 0
    error = None

    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": PROMPT}],
            max_tokens=max_tokens,
            temperature=0.0,
            stream=True,
        )

        async for chunk in stream:
            if first_token_time is None:
                first_token_time = time.perf_counter()
            if chunk.choices[0].delta.content:
                total_tokens += 1

    except Exception as e:
        error = str(e)

    end_time = time.perf_counter()

    ttft = first_token_time - start_time if first_token_time else float('inf')
    total_time = end_time - start_time
    decode_time = end_time - first_token_time if first_token_time else 0
    tps = total_tokens / decode_time if decode_time > 0 else 0

    return {
        "ttft": ttft,
        "total_time": total_time,
        "tokens": total_tokens,
        "tps": tps,
        "error": error,
    }

async def worker(requests_per_worker, max_tokens, model):
    """Execute multiple requests in sequence and return results."""
    results = []
    for _ in range(requests_per_worker):
        results.append(await single_request(model, max_tokens))
    return results

async def main():
    """Main benchmark function."""
    parser = argparse.ArgumentParser(description='Benchmark vLLM server performance')
    parser.add_argument('--concurrency', type=int, default=DEFAULT_CONCURRENCY, help='Number of concurrent workers')
    parser.add_argument('--requests', type=int, default=DEFAULT_REQUESTS_PER_WORKER, help='Requests per worker')
    parser.add_argument('--max-tokens', type=int, default=DEFAULT_MAX_TOKENS, help='Maximum tokens to generate')
    parser.add_argument('--output', type=str, help='Output file for results (JSON)')
    parser.add_argument('--warmup', type=int, default=1, help='Number of warmup requests')
    args = parser.parse_args()

        # Automatically select the first available model from the server
    model = await get_default_model()

    # Run warmup requests
    if args.warmup > 0:
        logging.info(f"Running {args.warmup} warmup request(s)...")
        warmup_tasks = [single_request(model, args.max_tokens) for _ in range(args.warmup)]
        await asyncio.gather(*warmup_tasks)

    logging.info(f"Running benchmark with concurrency={args.concurrency}, requests per worker={args.requests}, model={model}")
    tasks = [worker(args.requests, args.max_tokens, model) for _ in range(args.concurrency)]
    all_results = await asyncio.gather(*tasks)

    flat = [r for worker in all_results for r in worker]

    # Calculate statistics
    successful_requests = [r for r in flat if r['error'] is None]
    failed_requests = len(flat) - len(successful_requests)

    print("\n---- RESULTS ----")
    print(f"Total requests: {len(flat)}")
    print(f"Failed requests: {failed_requests}")
    if successful_requests:
        print(f"Avg TTFT: {statistics.mean(r['ttft'] for r in successful_requests):.3f}s")
        print(f"Avg total latency: {statistics.mean(r['total_time'] for r in successful_requests):.3f}s")
        print(f"Avg tokens/sec: {statistics.mean(r['tps'] for r in successful_requests):.2f}")
        print(f"P95 latency: {statistics.quantiles([r['total_time'] for r in successful_requests], n=20)[18]:.3f}s")
    else:
        print("No successful requests to calculate statistics")

    # Output to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump({
                "config": {
                    "concurrency": args.concurrency,
                    "requests_per_worker": args.requests,
                    "max_tokens": args.max_tokens,
                    "model": model,
                    "prompt": PROMPT,
                    "warmup": args.warmup
                },
                "results": flat,
                "summary": {
                    "total_requests": len(flat),
                    "successful_requests": len(successful_requests),
                    "failed_requests": failed_requests,
                    "avg_ttft": statistics.mean(r['ttft'] for r in successful_requests) if successful_requests else None,
                    "avg_latency": statistics.mean(r['total_time'] for r in successful_requests) if successful_requests else None,
                    "avg_tps": statistics.mean(r['tps'] for r in successful_requests) if successful_requests else None,
                    "p95_latency": statistics.quantiles([r['total_time'] for r in successful_requests], n=20)[18] if successful_requests else None
                }
            }, f, indent=2)
        print(f"\nResults saved to {args.output}")

if __name__ == "__main__":
    asyncio.run(main())
