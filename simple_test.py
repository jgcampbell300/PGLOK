#!/usr/bin/env python3
"""
Simple smoke test for the current PGLOK repository layout.

This repository does not include an addons/ package in this checkout, so the
previous addon-specific test was invalid here. This smoke test verifies that the
core app modules import cleanly in the active environment.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def main() -> int:
    print("Testing core imports...")

    try:
        import src.pglok  # noqa: F401
        import src.timer_window  # noqa: F401
        import src.chat_monitor  # noqa: F401
        print("Core imports successful")
    except Exception as exc:
        print(f"Core import failed: {exc}")
        raise

    print("Checking virtual environment...")
    print(f"Python executable: {sys.executable}")

    print("Smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
