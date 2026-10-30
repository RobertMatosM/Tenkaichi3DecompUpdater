"""Shared GitHub, archive, metadata, and install-registry helpers."""

from __future__ import annotations

from collections.abc import Callable
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath

import requests

REPO_OWNER = "z3xox"
REPO_NAME = "Tenkaichi3Decomp"
REPO_ASSET_NAME = "Tenkaichi3Decomp-linux-x64.zip"
METADATA_FILENAME = "Tenkaichi3DecompUpdater_meta.json"

APP_DATA_DIR = Path.home() / ".local" / "share" / "Tenkaichi3DecompUpdater"
INSTALLS_FILE = APP_DATA_DIR / "paths"
RELEASE_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
USER_AGENT = "Tenkaichi3DecompUpdater (Linux)"
EXECUTABLE_FILENAMES = ("Tenkaichi3Decomp", "Tenkaichi3Decomp-setup")
ProgressCallback = Callable[[int, int | None], None]


class ProgressDisplay:
    """Render byte progress in a terminal, or periodic updates in logs."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.started = time.monotonic()
        self.is_terminal = sys.stderr.isatty()
        self.last_reported_percent = -10
        self.last_reported_time = self.started
        self.rendered = False

    def update(self, completed: int, total: int | None = None) -> None:
        now = time.monotonic()
        elapsed = int(now - self.started)
        elapsed_text = f"{elapsed // 60:02d}:{elapsed % 60:02d}"

        if total:
            percent = min(100, int(completed * 100 / total))
            if self.is_terminal:
                if (
                    percent < self.last_reported_percent + 1
                    and now - self.last_reported_time < 0.1
                ):
                    return
            elif percent < self.last_reported_percent + 10:
                return
            self.last_reported_percent = percent
            self.last_reported_time = now
            bar_width = 24
            filled = int(bar_width * percent / 100)
            bar = "#" * filled + "-" * (bar_width - filled)
            message = (
                f"{self.label}: [{bar}] {percent:3d}% "
                f"({format_bytes(completed)} / {format_bytes(total)}) "
                f"{elapsed_text}"
            )
        else:
            if not self.is_terminal and now - self.last_reported_time < 5:
                return
            self.last_reported_time = now
            message = f"{self.label}: {format_bytes(completed)} {elapsed_text}"

        ending = "\r" if self.is_terminal else "\n"
        print(message, end=ending, file=sys.stderr, flush=True)
        self.rendered = True

    def finish(self, total: int | None = None) -> None:
        if total:
            self.update(total, total)
        elif not self.rendered:
            self.update(0, None)
        if self.is_terminal and self.rendered:
            print(file=sys.stderr, flush=True)


def format_bytes(value: int) -> str:
    """Format a byte count with a compact binary unit."""
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{value} B"
        amount /= 1024


def tree_size(root: Path) -> int:
    """Return the total size of regular files under a directory."""
    return sum(
        path.stat().st_size
        for directory, _, filenames in os.walk(root)
        for name in filenames
        for path in (Path(directory) / name,)
        if not path.is_symlink()
    )


def copy_file_with_progress(
    source: Path,
    destination: Path,
    progress: ProgressDisplay,
    completed: int,
    total: int,
) -> int:
    """Copy one regular file in chunks and update its progress display."""
    if source.is_symlink():
        shutil.copy2(source, destination, follow_symlinks=False)
        return completed

    with source.open("rb") as source_file, destination.open("wb") as output_file:
        while chunk := source_file.read(1024 * 64):
            output_file.write(chunk)
            completed += len(chunk)
            progress.update(completed, total if total > 0 else None)
    shutil.copystat(source, destination, follow_symlinks=False)
    return completed


def copy_tree_with_progress(source: Path, destination: Path) -> None:
    """Copy an installation tree while reporting progress for regular files."""
    total = tree_size(source)
    progress = ProgressDisplay("  Preserving existing files")
    progress.update(0, total if total > 0 else None)
    copied = 0

    def copy_file(source_name: str, destination_name: str) -> str:
        nonlocal copied
        copied = copy_file_with_progress(
            Path(source_name),
            Path(destination_name),
            progress,
            copied,
            total,
        )
        return destination_name

    shutil.copytree(
        source,
        destination,
        symlinks=True,
        copy_function=copy_file,
    )
    progress.finish(total if total > 0 else None)


def get_latest_release() -> tuple[dict, dict]:
    """Return the latest release JSON and this tool's Linux asset metadata."""
    response = requests.get(
        RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
        timeout=30,
    )
    response.raise_for_status()
    release = response.json()

    if not isinstance(release, dict):
        raise RuntimeError("GitHub returned an unexpected release response.")

    assets = release.get("assets", [])
    asset = next(
        (item for item in assets if item.get("name") == REPO_ASSET_NAME),
        None,
    )
    if asset is None:
        available = ", ".join(
            str(item.get("name", "<unnamed>")) for item in assets
        ) or "none"
        raise RuntimeError(
            f"Release {release.get('tag_name', '<unknown>')} does not contain "
            f"{REPO_ASSET_NAME}. Assets found: {available}"
        )

    if not asset.get("browser_download_url"):
        raise RuntimeError(f"The release asset {REPO_ASSET_NAME} has no download URL.")
    if not release.get("tag_name"):
        raise RuntimeError("GitHub's release response has no tag_name.")

    return release, asset


def download_asset(
    asset: dict,
    output_dir: Path,
    progress: ProgressCallback | None = None,
) -> Path:
    """Stream a release asset to disk rather than holding it all in memory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / REPO_ASSET_NAME

    with requests.get(
        asset["browser_download_url"],
        headers={"User-Agent": USER_AGENT},
        stream=True,
        timeout=(10, 60),
    ) as response:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        try:
            total = int(content_length) if content_length else int(asset.get("size", 0))
        except (TypeError, ValueError):
            total = 0
        total = total if total > 0 else None
        if progress is not None:
            progress(0, total)

        downloaded = 0
        with output_path.open("wb") as output_file:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    output_file.write(chunk)
                    downloaded += len(chunk)
                    if progress is not None:
                        progress(downloaded, total)

    return output_path


def safe_extract_zip(
    archive_path: Path,
    destination: Path,
    progress: ProgressCallback | None = None,
) -> None:
    """Extract a ZIP only if every member stays inside destination."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()

    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            # ZIP member paths use forward slashes. Check this form explicitly
            # before checking the resolved target on the Linux filesystem.
            member_name = member.filename
            posix_name = PurePosixPath(member_name)
            if posix_name.is_absolute() or ".." in posix_name.parts:
                raise RuntimeError(f"Unsafe path in release archive: {member_name!r}")

            target = (root / member_name).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise RuntimeError(
                    f"Unsafe path in release archive: {member_name!r}"
                ) from exc

        total = sum(member.file_size for member in archive.infolist())
        completed = 0
        if progress is not None:
            progress(0, total if total > 0 else None)

        for member in archive.infolist():
            target = root / member.filename
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output_file:
                while chunk := source.read(1024 * 64):
                    output_file.write(chunk)
                    completed += len(chunk)
                    if progress is not None:
                        progress(completed, total if total > 0 else None)

        if progress is not None and total == 0:
            progress(1, 1)


def make_release_executables(install_dir: Path) -> None:
    """Ensure the game and setup launchers from a release can be executed."""
    for filename in EXECUTABLE_FILENAMES:
        executable = install_dir / filename
        if not executable.is_file():
            raise RuntimeError(
                f"The release archive did not contain the expected file "
                f"{filename} in {install_dir}."
            )

        executable.chmod(stat.S_IMODE(executable.stat().st_mode) | 0o111)


def launch_setup(install_dir: Path) -> None:
    """Start the release's GUI setup in its installation directory."""
    setup_path = install_dir / "Tenkaichi3Decomp-setup"
    subprocess.Popen(
        [str(setup_path)],
        cwd=install_dir,
        start_new_session=True,
    )


def write_metadata(install_dir: Path, version: str) -> None:
    """Record the GitHub release tag installed at this path."""
    metadata_path = install_dir / METADATA_FILENAME
    metadata_path.write_text(
        json.dumps({"version": version}, indent=4) + "\n",
        encoding="utf-8",
    )


def read_installed_version(install_dir: Path) -> str | None:
    """Read a version tag, returning None if metadata is absent or invalid."""
    metadata_path = install_dir / METADATA_FILENAME
    if not metadata_path.is_file():
        return None

    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) and version.strip() else None


def read_install_paths() -> list[Path]:
    """Read and deduplicate the paths recorded by this updater."""
    if not INSTALLS_FILE.is_file():
        return []

    paths: list[Path] = []
    seen: set[Path] = set()
    for line in INSTALLS_FILE.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value:
            continue
        path = Path(value).expanduser().resolve()
        if path not in seen:
            paths.append(path)
            seen.add(path)
    return paths


def register_install(install_dir: Path) -> None:
    """Record one successful installation without adding duplicate entries."""
    install_dir = install_dir.expanduser().resolve()
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    paths = read_install_paths()
    if install_dir in paths:
        return

    with INSTALLS_FILE.open("a", encoding="utf-8") as registry:
        registry.write(f"{install_dir}\n")


def unregister_install(install_dir: Path) -> None:
    """Remove one installation path from the registry."""
    install_dir = install_dir.expanduser().resolve()
    remaining = [path for path in read_install_paths() if path != install_dir]
    INSTALLS_FILE.write_text(
        "".join(f"{path}\n" for path in remaining),
        encoding="utf-8",
    )
