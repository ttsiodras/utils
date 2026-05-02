#! /usr/bin/env python3
"""
Vibe-coded from Qwen3.5-122B. Works nicely!
"""
# pylint: disable=broad-exception-caught
# pylint: disable=too-many-locals

import sys
import asyncio
import json
import time
import argparse
import subprocess

import httpx

try:
    with httpx.Client() as client_model:
        model_response = client_model.get("http://127.0.0.1:8081/v1/models")
        model_response.raise_for_status()
        le_model = model_response.json()['data'][0]['id']
except Exception as e:
    print(f"There's, like, no model at port 8081, man...\n{e}\n")
    sys.exit(0)

async def send_request(client, url, prompt):
    payload = {
        "model": le_model, 
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0
    }
    try:
        start_time = time.perf_counter()
        response = await client.post(url, json=payload, timeout=120.0)
        response.raise_for_status()
        data = response.json()

        end_time = time.perf_counter()

        # Extract token usage from OpenAI-compatible response
        usage = data.get("usage", {})
        tokens = usage.get("completion_tokens", 0)

        return tokens, end_time - start_time
    except Exception as _:
        # print(f"Request failed: {_}")
        return 0, 0

def get_dataset(args):
    try:
        if args.dataset.endswith('.zst'):
            with subprocess.Popen(['zstdcat', args.dataset], stdout=subprocess.PIPE, text=True) as proc:
                if proc.stdout is None:
                    raise RuntimeError("Failed to capture stdout from zstdcat")
                return json.load(proc.stdout)
        else:
            with open(args.dataset, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading dataset: {e} - take it and zst compress it; it's here: "
              "https://huggingface.co/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered/resolve/"
              "main/ShareGPT_V3_unfiltered_cleaned_split.json")
        sys.exit(1)


def get_prompts(dataset):
    # Extract prompts from ShareGPT format
    prompts = []
    for entry in dataset:
        if "conversations" in entry:
            for msg in entry["conversations"]:
                if msg["from"] == "human":
                    prompts.append(msg["value"])
                    break

    if not prompts:
        print("No prompts found in dataset. Check your JSON format.")
        sys.exit(1)
    return prompts


async def main(args):
    dataset = get_dataset(args)
    prompts = get_prompts(dataset)

    print(f"Loaded {len(prompts)} prompts from {args.dataset}")
    print(f"Targeting: {args.url}")
    print(f"Concurrency: {args.concurrency}")
    print("-" * 40)

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=args.concurrency)) as client:
        total_tokens = 0
        completed_requests = 0
        start_bench = time.perf_counter()

        tasks = []

        # We use a semaphore to control concurrency strictly
        semaphore = asyncio.Semaphore(args.concurrency)

        async def sem_task(p):
            async with semaphore:
                return await send_request(client, args.url, p)

        print("Running benchmark...")

        # Create tasks for the specified number of prompts
        for i in range(min(args.num_prompts, len(prompts))):
            tasks.append(sem_task(prompts[i]))

        # Use tqdm-like progress reporting manually
        results = []
        for i, task in enumerate(asyncio.as_completed(tasks)):
            res = await task
            results.append(res)
            completed_requests += 1
            if completed_requests % 10 == 0 or completed_requests == min(args.num_prompts, len(prompts)):
                print(f"Progress: {completed_requests}/{min(args.num_prompts, len(prompts))} requests completed...", end="\r")

        end_bench = time.perf_counter()
        total_duration = end_bench - start_bench

        for tokens, _ in results:  # _ is duration, keep linter happy
            total_tokens += tokens

        print("\n" + "="*40)
        print("FINAL BENCHMARK RESULTS")
        print("="*40)
        print(f"Total Requests:    {completed_requests}")
        print(f"Total Tokens:      {total_tokens}")
        print(f"Total Time:        {total_duration:.2f} seconds")
        print(f"Throughput:        {total_tokens / total_duration:.2f} tokens/s")
        print(f"Avg Latency/Req:   {total_duration / completed_requests:.2f} s (approx)")
        print("="*40)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lightweight vLLM Client-side Benchmark")
    parser.add_argument("--url", type=str, help="vLLM endpoint (e.g. http://<IP>:8000/v1/chat/completions)", default='http://127.0.0.1:8081/v1/chat/completions')
    parser.add_argument("--dataset", type=str, help="Path to sharegpt_data.json (.json or .zst)", default='sharegpt_data.json.zst')
    parser.add_argument("--num-prompts", type=int, default=500, help="Number of prompts to run")
    parser.add_argument("--concurrency", type=int, default=64, help="Number of simultaneous requests")

    le_args = parser.parse_args()
    asyncio.run(main(le_args))
