#!/usr/bin/env python3
"""
Simple minion integration test.

Sends a basic instruction to the running Basil API and validates the response.
Requires the Basil backend to be running on localhost:8000.

Usage:
    python src/tests/services/voice_listener_tests/test_minion_simple.py
    python src/tests/services/voice_listener_tests/test_minion_simple.py --model Qwen-qwen3-8b-instruct-q4km
"""

import argparse
import json
import sys
import time

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests")
    sys.exit(1)

BASE_URL = "http://127.0.0.1:8000"
ENDPOINT = f"{BASE_URL}/api/v1/voice-listener/process-prompt"
TIMEOUT_SECONDS = 600

TEST_INSTRUCTION = "List all the services that Basil provides and briefly describe what each one does."


def run_test(model_id: str = None):
    payload = {"instruction": TEST_INSTRUCTION}
    if model_id:
        payload["model_id"] = model_id

    print(f"Instruction:  \"{TEST_INSTRUCTION}\"")
    if model_id:
        print(f"Model:    {model_id}")
    print(f"Endpoint: {ENDPOINT}")
    print(f"Timeout:  {TIMEOUT_SECONDS}s")
    print("-" * 60)

    start = time.time()
    try:
        resp = requests.post(ENDPOINT, json=payload, timeout=TIMEOUT_SECONDS)
    except requests.ConnectionError:
        print(f"FAIL: Cannot connect to {BASE_URL}. Is Basil running?")
        sys.exit(1)
    except requests.Timeout:
        print(f"FAIL: Request timed out after {time.time() - start:.1f}s")
        sys.exit(1)
    elapsed = time.time() - start

    content_type = resp.headers.get("content-type", "")

    if "application/x-ndjson" in content_type:
        lines = resp.text.strip().splitlines()
        chunks = [json.loads(line) for line in lines if line.strip()]
        print(f"HTTP {resp.status_code}  ({elapsed:.1f}s)  [streamed {len(chunks)} chunks]")
        for i, chunk in enumerate(chunks):
            print(f"  [{i}] {json.dumps(chunk, indent=2)}")
        return

    try:
        body = resp.json()
    except Exception:
        print(f"HTTP {resp.status_code}  ({elapsed:.1f}s)")
        print(f"Raw response: {resp.text[:500]}")
        sys.exit(1)

    print(f"HTTP {resp.status_code}  ({elapsed:.1f}s)")
    print(json.dumps(body, indent=2, default=str))

    if isinstance(body, dict):
        success = body.get("success")
        message = body.get("message", "")
        reasoning = body.get("reasoning", "")
        if success is False:
            print(f"\nFAILED: {message}")
            if reasoning:
                print(f"Reason:  {reasoning}")
            sys.exit(1)
        elif success is True:
            print(f"\nPASSED: {message}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test a minion against the Basil API")
    parser.add_argument("--model", type=str, default=None, help="Model ID to override (e.g. Qwen-qwen3-8b-instruct-q4km)")
    args = parser.parse_args()
    run_test(model_id=args.model)
