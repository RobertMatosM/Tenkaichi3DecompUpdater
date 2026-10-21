from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from common import METADATA_FILENAME, read_installed_version, safe_extract_zip, write_metadata
from update import normalized_version, preserve_user_data


class UpdaterTests(unittest.TestCase):
    def test_metadata_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            install_dir = Path(temporary_dir)
            write_metadata(install_dir, "v0.1.38")
            self.assertEqual(read_installed_version(install_dir), "v0.1.38")
            self.assertEqual(
                json.loads((install_dir / METADATA_FILENAME).read_text())["version"],
                "v0.1.38",
            )

    def test_safe_zip_extract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            archive_path = root / "release.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("Tenkaichi3Decomp/readme.txt", "hello")
            output_dir = root / "out"
            safe_extract_zip(archive_path, output_dir)
            self.assertEqual(
                (output_dir / "Tenkaichi3Decomp" / "readme.txt").read_text(),
                "hello",
            )

    def test_unsafe_zip_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            archive_path = root / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "nope")
            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                safe_extract_zip(archive_path, root / "out")
            self.assertFalse((root / "escape.txt").exists())

    def test_user_data_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            old_install = root / "old"
            new_install = root / "new"
            (old_install / "saves").mkdir(parents=True)
            (old_install / "saves" / "slot.dat").write_text("user save")
            (old_install / "bt3_settings.txt").write_text("my settings")
            (new_install / "saves").mkdir(parents=True)
            (new_install / "saves" / "default.dat").write_text("release default")
            (new_install / "bt3_settings.txt").write_text("release default settings")

            preserve_user_data(old_install, new_install)
            self.assertEqual((new_install / "saves" / "slot.dat").read_text(), "user save")
            self.assertFalse((new_install / "saves" / "default.dat").exists())
            self.assertEqual((new_install / "bt3_settings.txt").read_text(), "my settings")

    def test_release_versions_compare(self) -> None:
        self.assertGreater(normalized_version("v0.1.38"), normalized_version("v0.1.37.1"))


if __name__ == "__main__":
    unittest.main()
