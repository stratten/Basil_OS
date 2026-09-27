#!/usr/bin/env python3
"""
Debug script to understand the import system in the project.
"""

import os
import sys
from pathlib import Path

# Print the current Python path
print("\nCurrent sys.path:")
for p in sys.path:
    print(f"  {p}")

# Try different import approaches
print("\nAttempting imports...")

# First, add the src directory to the path (similar to test_api_models.py)
src_path = Path(__file__).parent.parent / "src"
sys.path.append(str(src_path))
print(f"\nAdded {src_path} to sys.path")

# Try importing with absolute imports
try:
    from config.api_keys import get_api_key
    print("✓ Successfully imported 'from config.api_keys import get_api_key'")
except ImportError as e:
    print(f"✗ Failed to import 'from config.api_keys import get_api_key': {e}")

# Try importing from the Basil package
try:
    from config.api_keys import get_api_key
    print("✓ Successfully imported 'from config.api_keys import get_api_key'")
except ImportError as e:
    print(f"✗ Failed to import 'from config.api_keys import get_api_key': {e}")

# Try a relative import from the test directory
try:
    from ..src.config.api_keys import get_api_key
    print("✓ Successfully imported 'from ..src.config.api_keys import get_api_key'")
except ImportError as e:
    print(f"✗ Failed to import 'from ..src.config.api_keys import get_api_key': {e}")

print("\nFinished import tests.") 