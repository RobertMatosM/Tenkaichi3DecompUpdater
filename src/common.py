"""Shared GitHub, archive, metadata, and install-registry helpers."""

from __future__ import annotations

import json
import stat
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

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


def download_asset(asset: dict, output_dir: Path) -> Path:
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
        with output_path.open("wb") as output_file:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    output_file.write(chunk)

    return output_path


def safe_extract_zip(archive_path: Path, destination: Path) -> None:
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

        archive.extractall(root)


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
