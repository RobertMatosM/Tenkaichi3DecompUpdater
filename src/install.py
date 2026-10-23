#!/usr/bin/env python3
"""Install the latest Linux release into a chosen parent directory."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import tempfile

import requests

from common import (
    REPO_NAME,
    download_asset,
    get_latest_release,
    launch_setup,
    make_release_executables,
    register_install,
    safe_extract_zip,
    write_metadata,
)


def choose_parent_dir(argument: Path | None) -> Path:
    if argument is not None:
        return argument.expanduser().resolve()

    default = Path.home() / "Games"
    entered = input(f"Parent directory for the installation [{default}]: ").strip()
    selected = Path(entered).expanduser() if entered else default
    return selected.resolve()


def install(parent_dir: Path) -> Path:
    parent_dir.mkdir(parents=True, exist_ok=True)
    install_dir = parent_dir / REPO_NAME

    if install_dir.exists():
        raise FileExistsError(
            f"{install_dir} already exists. Choose another parent directory "
            "or move/rename the existing installation first."
        )

    print("Checking the latest GitHub release...")
    release, asset = get_latest_release()
    version = release["tag_name"]

    # Keep staging on the same filesystem as the final directory so the final
    # rename is fast and does not leave a half-copied installation.
    with tempfile.TemporaryDirectory(
        prefix=".bt3-updater-install-", dir=parent_dir
    ) as temporary_dir:
        staging = Path(temporary_dir)
        archive_path = download_asset(asset, staging)
        extracted_dir = staging / "extracted"
        print(f"Extracting release {version}...")
        safe_extract_zip(archive_path, extracted_dir)

        staged_install = extracted_dir / REPO_NAME
        if not staged_install.is_dir():
            raise RuntimeError(
                f"The release archive did not contain the expected directory "
                f"{REPO_NAME}/. The archive layout may have changed."
            )

        make_release_executables(staged_install)
        write_metadata(staged_install, version)
        staged_install.rename(install_dir)

    register_install(install_dir)
    launch_setup(install_dir)
    print(f"Installed {REPO_NAME} {version} at {install_dir}")
    return install_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parent",
        type=Path,
        help=f"Parent directory; {REPO_NAME}/ will be created inside it.",
    )
    args = parser.parse_args()

    try:
        install(choose_parent_dir(args.parent))
    except (OSError, RuntimeError, requests.RequestException, ValueError) as exc:
        print(f"Install failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
