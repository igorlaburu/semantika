#!/usr/bin/env python3
"""Quick SSH test script to bypass shell issues."""

import subprocess
import sys

# SSH command
cmd = [
    "ssh",
    "-i", "/Users/igor/.ssh/semantika_vps",
    "-o", "StrictHostKeyChecking=no",
    "ubuntu@api.ekimen.ai",
    "docker logs --tail 50 semantika-scheduler 2>&1 | grep -i dfa"
]

try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    print("STDOUT:")
    print(result.stdout)
    print("\nSTDERR:")
    print(result.stderr)
    print(f"\nReturn code: {result.returncode}")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
