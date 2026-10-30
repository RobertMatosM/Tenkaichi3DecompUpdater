#!/usr/bin/env python3
"""Update installations registered by Tenkaichi3DecompUpdater."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
from pathlib import Path
import shutil
import sys
import tempfile

from packaging.version import InvalidVersion, Version
import requests

from common import (
    LabeledProgressCallback,
    METADATA_FILENAME,
    ProgressDisplay,
    REPO_NAME,
    copy_file_with_progress,
    copy_tree_with_progress,
    download_asset,
    get_latest_release,
    launch_setup,
    make_release_executables,
    read_install_paths,
    read_installed_version,
    safe_extract_zip,
    tree_size,
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


def remove_path(path: Path) -> None:
    """Remove a file, directory, or symlink before replacing it."""
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def overlay_install(
    source: Path,
    destination: Path,
    progress_callback: LabeledProgressCallback | None = None,
) -> None:
    """Copy release files over an install while leaving unrelated files intact."""
    total = tree_size(source)
    progress = ProgressDisplay("Applying release files", progress_callback)
    progress.update(0, total if total > 0 else None)
    copied = 0

    def overlay_directory(source_dir: Path, destination_dir: Path) -> None:
        nonlocal copied
        for source_path in source_dir.iterdir():
            destination_path = destination_dir / source_path.name
            if source_path.is_dir() and not source_path.is_symlink():
                if destination_path.is_symlink() or (
                    destination_path.exists() and not destination_path.is_dir()
                ):
                    remove_path(destination_path)
                destination_path.mkdir(exist_ok=True)
                overlay_directory(source_path, destination_path)
            else:
                if destination_path.exists() or destination_path.is_symlink():
                    remove_path(destination_path)
                copied = copy_file_with_progress(
                    source_path,
                    destination_path,
                    progress,
                    copied,
                    total,
                )

    overlay_directory(source, destination)
    progress.finish(total if total > 0 else None)


def check_one(install_dir: Path, latest_version: str) -> str:
    """Describe whether one registered installation has an update available."""
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

    if current_version == latest_parsed:
        return f"Already up to date: {install_dir} ({current_tag})"
    if current_version > latest_parsed:
        return (
            f"Installed version {current_tag} is newer than GitHub's latest "
            f"{latest_version}: {install_dir}"
        )
    return f"Update available: {install_dir} ({current_tag} -> {latest_version})"


def update_one(
    install_dir: Path,
    latest_version: str,
    archive_path: Path,
    on_message: Callable[[str], None] | None = None,
    on_progress: LabeledProgressCallback | None = None,
) -> str:
    """Stage and swap one installation, rolling back if the swap fails."""
    emit = on_message or print
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
        emit(f"  Extracting release {latest_version}...")
        extraction_progress = ProgressDisplay("Extraction", on_progress)
        safe_extract_zip(
            archive_path,
            extracted_dir,
            extraction_progress.update,
        )
        extraction_progress.finish()
        staged_install = extracted_dir / REPO_NAME
        if not staged_install.is_dir():
            raise RuntimeError(
                f"The release archive did not contain the expected directory "
                f"{REPO_NAME}/."
            )

        make_release_executables(staged_install)
        preserve_user_data(install_dir, staged_install)
        write_metadata(staged_install, latest_version)

        # Preserve the current tree, then overwrite paths supplied by the new
        # release. Files that the release no longer contains remain installed.
        merged_install = staging / "merged-install"
        copy_tree_with_progress(install_dir, merged_install, on_progress)
        overlay_install(staged_install, merged_install, on_progress)

        # Both paths are on the same filesystem. Move the old install aside,
        # then swap in the staged overlay. Restore the old directory on failure.
        old_install_backup = staging / "previous-install"
        try:
            install_dir.rename(old_install_backup)
        except OSError as exc:
            if sys.platform == "win32":
                raise RuntimeError(
                    f"Windows could not replace {install_dir}. Close the game and "
                    "setup window, then try the update again."
                ) from exc
            raise
        try:
            merged_install.rename(install_dir)
        except Exception:
            try:
                old_install_backup.rename(install_dir)
            except OSError as rollback_error:
                raise RuntimeError(
                    f"The update swap failed and the previous installation could "
                    f"not be restored automatically. Its backup is at "
                    f"{old_install_backup}."
                ) from rollback_error
            raise

    launch_setup(install_dir)
    return f"Updated {install_dir}: {current_tag} -> {latest_version}"


def update_installations(
    check_only: bool = False,
    on_message: Callable[[str], None] | None = None,
    on_progress: LabeledProgressCallback | None = None,
) -> int:
    """Check or update every registered install, reporting optional UI events."""
    emit = on_message or print
    try:
        install_paths = read_install_paths()
        if not install_paths:
            emit("No installations are registered yet.")
            return 0

        step_count = 1 if check_only else 4
        emit(f"[1/{step_count}] Looking up the latest GitHub release...")
        release, asset = get_latest_release()
        latest_version = release["tag_name"]

        if check_only:
            emit(f"Latest release: {latest_version}")
            for install_dir in install_paths:
                emit(check_one(install_dir, latest_version))
            return 0

        # Download once and reuse the archive for every registered installation.
        with tempfile.TemporaryDirectory(prefix=".bt3-updater-download-") as temp:
            emit(f"[2/4] Downloading release {latest_version}...")
            download_progress = ProgressDisplay("Download", on_progress)
            archive_path = download_asset(
                asset,
                Path(temp),
                download_progress.update,
            )
            download_progress.finish()
            failures = 0
            for index, install_dir in enumerate(install_paths, start=1):
                try:
                    emit(
                        f"[3/4] Processing installation {index}/"
                        f"{len(install_paths)}: {install_dir}"
                    )
                    emit(
                        update_one(
                            install_dir,
                            latest_version,
                            archive_path,
                            emit,
                            on_progress,
                        )
                    )
                except (
                    OSError,
                    RuntimeError,
                    requests.RequestException,
                    ValueError,
                ) as exc:
                    failures += 1
                    emit(f"Failed to update {install_dir}: {exc}")

            emit("[4/4] Update run complete.")

        return 1 if failures else 0
    except (OSError, RuntimeError, requests.RequestException, ValueError) as exc:
        emit(f"Update failed: {exc}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Check for available updates without downloading or installing them.",
    )
    args = parser.parse_args()

    def report(message: str) -> None:
        if message.startswith(("Failed to update", "Update failed:")):
            print(message, file=sys.stderr)
        else:
            print(message)

    return update_installations(args.check_only, report)


if __name__ == "__main__":
    raise SystemExit(main())
