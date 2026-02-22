import asyncio
import time
import statistics
from openai import AsyncOpenAI

# ---- CONFIG ----
BASE_URL = "http://172.17.0.1:8000/v1"
API_KEY = "EMPTY"  # vLLM doesn't require a real key
MODEL = "dazipe/Qwen3-Next-80B-A3B-Instruct-GPTQ-Int4A16"
# MODEL = "openai/gpt-oss-120b"

CONCURRENCY = 8
REQUESTS_PER_WORKER = 4
MAX_TOKENS = 512
PROMPT = "Write a detailed technical explanation of how KV caching works in transformer inference."

# ----------------

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
)

async def single_request():
    start_time = time.perf_counter()

    first_token_time = None
    total_tokens = 0

    stream = await client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": PROMPT}],
        max_tokens=MAX_TOKENS,
        temperature=0.0,
        stream=True,
    )

    async for chunk in stream:
        if first_token_time is None:
            first_token_time = time.perf_counter()
        if chunk.choices[0].delta.content:
            total_tokens += 1

    end_time = time.perf_counter()

    ttft = first_token_time - start_time
    total_time = end_time - start_time
    decode_time = end_time - first_token_time if first_token_time else 0
    tps = total_tokens / decode_time if decode_time > 0 else 0

    return {
        "ttft": ttft,
        "total_time": total_time,
        "tokens": total_tokens,
        "tps": tps,
    }

async def worker():
    results = []
    for _ in range(REQUESTS_PER_WORKER):
        results.append(await single_request())
    return results

async def main():
    print(f"Running benchmark with concurrency={CONCURRENCY}")
    tasks = [worker() for _ in range(CONCURRENCY)]
    all_results = await asyncio.gather(*tasks)

    flat = [r for worker in all_results for r in worker]

    print("\n---- RESULTS ----")
    print(f"Total requests: {len(flat)}")
    print(f"Avg TTFT: {statistics.mean(r['ttft'] for r in flat):.3f}s")
    print(f"Avg total latency: {statistics.mean(r['total_time'] for r in flat):.3f}s")
    print(f"Avg tokens/sec: {statistics.mean(r['tps'] for r in flat):.2f}")
    print(f"P95 latency: {statistics.quantiles([r['total_time'] for r in flat], n=20)[18]:.3f}s")

if __name__ == "__main__":
    asyncio.run(main())
