#!/usr/bin/env python3
"""Project launcher for Tenkaichi3DecompUpdater (Linux)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import subprocess
import sys
import venv

PROJECT_DIR = Path(__file__).resolve().parent
VENV_DIR = PROJECT_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
REQUIREMENTS = PROJECT_DIR / "requirements.txt"

LOGGER = logging.getLogger("Tenkaichi3DecompUpdater")


def ensure_venv() -> None:
    """Create the project virtual environment if its Python is missing."""
    if VENV_PYTHON.is_file():
        return

    LOGGER.info("Creating virtual environment at %s", VENV_DIR)
    VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    venv.create(VENV_DIR, with_pip=True)

    if not VENV_PYTHON.is_file():
        raise RuntimeError(f"Could not find virtual-environment Python at {VENV_PYTHON}")


def run_checked(command: list[str | Path]) -> None:
    """Run a child process and stop if it fails."""
    subprocess.run([str(part) for part in command], cwd=PROJECT_DIR, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="Tenkaichi3DecompUpdater",
        description="Install or update Tenkaichi3Decomp from its GitHub releases.",
    )
    parser.add_argument(
        "action",
        type=str.lower,
        choices=("i", "install", "u", "update", "t", "test"),
        help="Action to run: install (i), update (u), or test (t).",
    )
    args, child_args = parser.parse_known_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    try:
        ensure_venv()

        # Running pip through this Python guarantees that dependencies go into
        # this project's venv; pip itself parses requirements.txt correctly.
        if REQUIREMENTS.is_file():
            run_checked([VENV_PYTHON, "-m", "pip", "install", "-r", REQUIREMENTS])
        else:
            LOGGER.warning("No requirements.txt found; skipping dependency installation.")

        action_to_script = {
            "i": PROJECT_DIR / "src" / "install.py",
            "install": PROJECT_DIR / "src" / "install.py",
            "u": PROJECT_DIR / "src" / "update.py",
            "update": PROJECT_DIR / "src" / "update.py",
            "t": PROJECT_DIR / "test.py",
            "test": PROJECT_DIR / "test.py",
        }
        script = action_to_script[args.action]
        if not script.is_file():
            raise FileNotFoundError(f"Script not found: {script}")

        run_checked([VENV_PYTHON, script, *child_args])
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        LOGGER.error("Operation failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
