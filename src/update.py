#!/usr/bin/env python3
"""Update installations registered by bt3DecompUpdater."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile

from packaging.version import InvalidVersion, Version
import requests

from common import (
    METADATA_FILENAME,
    REPO_NAME,
    download_asset,
    get_latest_release,
    read_install_paths,
    read_installed_version,
    safe_extract_zip,
    write_metadata,
)

# These user-data paths are copied from the old installation into the staged
# release. This includes the game's settings file, which lives beside the binary.
# Add/remove relative paths here to choose what survives an update.
PRESERVE_PATHS = ("textures", "saves", "bt3_settings.txt")


def normalized_version(tag: str) -> Version:
    """Parse release tags such as v0.1.38 as comparable versions."""
    return Version(tag.strip().lstrip("vV"))


def preserve_user_data(old_install: Path, new_install: Path) -> None:
    for relative_name in PRESERVE_PATHS:
        old_path = old_install / relative_name
        if not old_path.exists():
            continue

        new_path = new_install / relative_name
        if new_path.is_dir():
            shutil.rmtree(new_path)
        elif new_path.exists():
            new_path.unlink()

        if old_path.is_dir():
            shutil.copytree(old_path, new_path)
        else:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old_path, new_path)


def update_one(
    install_dir: Path,
    latest_version: str,
    archive_path: Path,
) -> str:
    """Stage and swap one installation, rolling back if the swap fails."""
    if not install_dir.is_dir():
        return f"Skipping missing installation: {install_dir}"

    current_tag = read_installed_version(install_dir)
    if current_tag is None:
        return (
            f"Skipping {install_dir}: missing or invalid {METADATA_FILENAME}. "
            "Reinstall/register it manually before updating."
        )

    try:
        current_version = normalized_version(current_tag)
        latest_parsed = normalized_version(latest_version)
    except InvalidVersion:
        return (
            f"Skipping {install_dir}: cannot compare version tags "
            f"{current_tag!r} and {latest_version!r}."
        )

    if current_version >= latest_parsed:
        if current_version == latest_parsed:
            return f"Already up to date: {install_dir} ({current_tag})"
        return (
            f"Skipping {install_dir}: installed version {current_tag} is newer "
            f"than GitHub's latest {latest_version}; refusing to downgrade."
        )

    parent_dir = install_dir.parent
    with tempfile.TemporaryDirectory(
        prefix=".bt3-updater-update-", dir=parent_dir
    ) as temporary_dir:
        staging = Path(temporary_dir)
        extracted_dir = staging / "extracted"
        safe_extract_zip(archive_path, extracted_dir)
        staged_install = extracted_dir / REPO_NAME
        if not staged_install.is_dir():
            raise RuntimeError(
                f"The release archive did not contain the expected directory "
                f"{REPO_NAME}/."
            )

        preserve_user_data(install_dir, staged_install)
        write_metadata(staged_install, latest_version)

        # Both paths are on the same filesystem. Move the old install aside,
        # then swap in the staged one. Restore the old directory on failure.
        old_install_backup = staging / "previous-install"
        install_dir.rename(old_install_backup)
        try:
            staged_install.rename(install_dir)
        except Exception:
            old_install_backup.rename(install_dir)
            raise

    return f"Updated {install_dir}: {current_tag} -> {latest_version}"


def main() -> int:
    try:
        install_paths = read_install_paths()
        if not install_paths:
            print("No installations are registered yet.")
            return 0

        print("Checking the latest GitHub release...")
        release, asset = get_latest_release()
        latest_version = release["tag_name"]

        # Download once and reuse the archive for every registered installation.
        with tempfile.TemporaryDirectory(prefix=".bt3-updater-download-") as temp:
            archive_path = download_asset(asset, Path(temp))
            failures = 0
            for install_dir in install_paths:
                try:
                    print(update_one(install_dir, latest_version, archive_path))
                except (
                    OSError,
                    RuntimeError,
                    requests.RequestException,
                    ValueError,
                ) as exc:
                    failures += 1
                    print(f"Failed to update {install_dir}: {exc}", file=sys.stderr)

        return 1 if failures else 0
    except (OSError, RuntimeError, requests.RequestException, ValueError) as exc:
        print(f"Update failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
