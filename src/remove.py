#!/usr/bin/env python3
"""Interactively remove a registered Tenkaichi3Decomp installation."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys

from common import REPO_NAME, read_install_paths, unregister_install


def choose_install(install_paths: list[Path]) -> Path | None:
    print("Registered installations:")
    for index, install_dir in enumerate(install_paths, start=1):
        status = "" if install_dir.is_dir() else " (missing)"
        print(f"  {index}. {install_dir}{status}")

    while True:
        choice = input("Choose an installation to remove, or q to cancel: ").strip()
        if choice.lower() in ("q", "quit", "cancel"):
            return None
        try:
            selected_index = int(choice)
        except ValueError:
            print("Enter an installation number or q to cancel.")
            continue
        if 1 <= selected_index <= len(install_paths):
            return install_paths[selected_index - 1]
        print(f"Choose a number from 1 to {len(install_paths)}, or q to cancel.")


def confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N]: ").strip().lower() in ("y", "yes")


def remove_registered_install(install_dir: Path) -> list[str]:
    """Remove one registered installation and its registry entry."""
    install_dir = install_dir.expanduser().resolve()
    if install_dir.name != REPO_NAME:
        raise ValueError(
            f"Refusing to remove {install_dir}: registered installation paths "
            f"must end in {REPO_NAME}/."
        )

    messages = []
    if install_dir.is_dir():
        shutil.rmtree(install_dir)
        messages.append(f"Removed installation files at {install_dir}")
    elif install_dir.exists():
        raise ValueError(
            f"Refusing to remove {install_dir}: the registered path is not a directory."
        )

    unregister_install(install_dir)
    messages.append(f"Removed {install_dir} from the installation registry.")
    return messages


def remove_installation() -> int:
    install_paths = read_install_paths()
    if not install_paths:
        print("No installations are registered.")
        return 0

    install_dir = choose_install(install_paths)
    if install_dir is None:
        print("Removal cancelled.")
        return 0

    if install_dir.is_dir():
        prompt = f"Permanently remove {install_dir} and its files?"
    else:
        prompt = f"Remove the stale registry entry for {install_dir}?"
    if not confirm(prompt):
        print("Removal cancelled.")
        return 0

    try:
        for message in remove_registered_install(install_dir):
            print(message)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def main() -> int:
    try:
        return remove_installation()
    except (EOFError, OSError, ValueError) as exc:
        print(f"Removal failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
