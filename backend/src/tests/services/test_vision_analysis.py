#!/usr/bin/env python3
"""
Vision Analysis — End-to-End Test via Minion Endpoint

Submits a text instruction to the running Basil backend through the same
POST /api/v1/voice-listener/process-prompt endpoint that a spoken
minion uses. This lets you test the full pipeline — routing,
agent graph, tool discovery, vision tool invocation — without having
to speak the instruction each time.

Requires the Basil backend to be running (port auto-detected from
the server_port file, or override with --port).

Usage (from the Basil/ directory):

    # Default: ask the agent to extract books from ~/Desktop/workspace
    poetry run python src/tests/services/test_vision_analysis.py

    # Point at a different image directory:
    poetry run python src/tests/services/test_vision_analysis.py --dir /path/to/images

    # Supply a completely custom instruction:
    poetry run python src/tests/services/test_vision_analysis.py --instruction "Describe the first 3 images in ~/Desktop/workspace"

    # Override backend port:
    poetry run python src/tests/services/test_vision_analysis.py --port 8001

    # Pass the image directory as reference_paths context (drag-and-drop equivalent):
    poetry run python src/tests/services/test_vision_analysis.py --with-ref-paths
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    sys.exit("httpx is required.  Install with:  pip install httpx")


# ===================================================================
# Port discovery
# ===================================================================

def _discover_port() -> int:
    """Read the backend port from the server_port file written at startup."""
    candidates = [
        Path.home() / "Library" / "Application Support" / "Basil" / "server_port",
        Path(__file__).resolve().parent.parent.parent.parent / ".server_port",
    ]
    for p in candidates:
        if p.exists():
            try:
                return int(p.read_text().strip())
            except ValueError:
                continue
    return 8000  # fallback default


# ===================================================================
# Default instruction text
# ===================================================================

DEFAULT_IMAGE_DIR = str(Path.home() / "Desktop" / "workspace")

DEFAULT_INSTRUCTION = (
    "Look at the images in {dir} and extract every book title and author you can "
    "identify. Write the results to a CSV file in that same directory called "
    "book_list.csv with columns: filename, title, author. Process them in small "
    "batches using your vision analysis capabilities — do not use OCR or write "
    "external scripts."
)


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Submit a minion to the running Basil backend and stream "
            "the response — same entry point as a spoken instruction."
        )
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Backend port (auto-detected from server_port file if omitted)",
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=DEFAULT_IMAGE_DIR,
        help=f"Image directory to reference in the default instruction (default: {DEFAULT_IMAGE_DIR})",
    )
    parser.add_argument(
        "--instruction",
        type=str,
        default=None,
        help="Custom instruction text (overrides the default book-extraction instruction)",
    )
    parser.add_argument(
        "--with-ref-paths",
        action="store_true",
        help="Also pass --dir as reference_paths (simulates drag-and-drop)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="HTTP timeout in seconds (default: 600 = 10 min, these can be long-running)",
    )
    args = parser.parse_args()

    port = args.port or _discover_port()
    base_url = f"http://localhost:{port}"
    endpoint = f"{base_url}/api/v1/voice-listener/process-prompt"

    # Build instruction text
    instruction = args.instruction or DEFAULT_INSTRUCTION.format(dir=args.dir)

    # Build request payload — matches TextPromptRequest schema
    payload: dict = {"instruction": instruction}
    if args.with_ref_paths:
        payload["reference_paths"] = [args.dir]

    print("=" * 70)
    print("BASIL VOICE INSTRUCTION — END-TO-END TEST")
    print("=" * 70)
    print(f"Backend:  {base_url}")
    print(f"Endpoint: {endpoint}")
    print(f"Instruction:  {instruction}")
    if args.with_ref_paths:
        print(f"Ref paths: {payload['reference_paths']}")
    print(f"Timeout:  {args.timeout}s")
    print("=" * 70)
    print()

    # ---- Check backend is reachable ----
    try:
        with httpx.Client(timeout=5.0) as check_client:
            health = check_client.get(f"{base_url}/health")
            if health.status_code != 200:
                print(f"WARNING: /health returned {health.status_code}")
    except httpx.ConnectError:
        sys.exit(
            f"Cannot connect to backend at {base_url}.\n"
            "Make sure the Basil backend is running (poetry run python src/basil_api.py)."
        )

    # ---- Submit the instruction ----
    t0 = time.monotonic()
    print("Submitting instruction...\n")

    try:
        with httpx.Client(timeout=args.timeout) as client:
            response = client.post(
                endpoint,
                json=payload,
                timeout=args.timeout,
            )
    except httpx.ReadTimeout:
        elapsed = time.monotonic() - t0
        sys.exit(
            f"\nRequest timed out after {elapsed:.0f}s. "
            f"Increase with --timeout or check backend logs."
        )

    elapsed = time.monotonic() - t0

    # ---- Parse response ----
    print(f"Response received in {elapsed:.1f}s  (HTTP {response.status_code})")
    print("-" * 70)

    content_type = response.headers.get("content-type", "")

    if "application/x-ndjson" in content_type:
        # Streaming response — parse each NDJSON line
        print("(Streaming response — showing chunks)\n")
        for line in response.text.strip().splitlines():
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
                stage = chunk.get("stage", "")
                complete = chunk.get("complete", False)

                if stage:
                    status = "DONE" if complete else "..."
                    print(f"  [{status}] {stage}")

                # Print final result if present
                result = chunk.get("result") or chunk.get("data") or chunk.get("message")
                if result and complete:
                    print(f"\n{'='*70}")
                    print("AGENT RESULT:")
                    print("=" * 70)
                    if isinstance(result, dict):
                        print(json.dumps(result, indent=2))
                    else:
                        print(result)

                # Print errors
                if chunk.get("error"):
                    print(f"\n  ERROR: {chunk['error']}")

            except json.JSONDecodeError:
                print(f"  (raw line) {line}")
    else:
        # JSON response
        try:
            data = response.json()
            print()
            print(f"  Success:    {data.get('success')}")
            print(f"  Operation:  {data.get('operation')}")
            print(f"  Confidence: {data.get('confidence')}")
            print(f"  Instruction ID: {data.get('agent_task_id')}")
            print(f"  Proc Time:  {data.get('processing_time', 0):.1f}s")
            print()

            message = data.get("message", "")
            reasoning = data.get("reasoning", "")

            if reasoning:
                print("REASONING:")
                print("-" * 40)
                print(reasoning)
                print()

            if message:
                print("MESSAGE:")
                print("-" * 40)
                print(message)
                print()

            # Pretty-print the full response for debugging
            print("FULL RESPONSE:")
            print("-" * 40)
            print(json.dumps(data, indent=2))

        except json.JSONDecodeError:
            print("(Raw text response)")
            print(response.text)

    print()
    print("=" * 70)
    print(f"Total elapsed: {elapsed:.1f}s")
    print("=" * 70)

    # Remind about logs
    print("\nCheck backend logs for detailed agent execution trace.")
    if data := (response.json() if "json" in content_type else None):
        cmd_id = data.get("agent_task_id")
        if cmd_id:
            print(f"Instruction ID: {cmd_id}")
            print(f"View details: GET {base_url}/api/v1/voice-listener/instruction/{cmd_id}")


if __name__ == "__main__":
    main()
