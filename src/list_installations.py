#!/usr/bin/env python3
"""List registered Tenkaichi3Decomp installation paths."""

from __future__ import annotations

from common import read_install_paths


def main() -> int:
    install_paths = read_install_paths()
    if not install_paths:
        print("No installations are registered.")
        return 0

    print("Registered installations:")
    for install_dir in install_paths:
        status = "" if install_dir.is_dir() else " (missing)"
        print(f"- {install_dir}{status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
