#!/usr/bin/env python3
"""Run the updater's local unit tests without contacting GitHub."""

from pathlib import Path
import sys
import unittest

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR / "src"))

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(PROJECT_DIR / "tests"),
        pattern="test_*.py",
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
