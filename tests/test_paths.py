"""Path selection tests: bundled resources vs. writable user data."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from petapp import paths

ROOT = Path(__file__).resolve().parents[1]


class PathTests(unittest.TestCase):
    def make_temp_dir(self) -> Path:
        folder = Path(tempfile.mkdtemp(prefix="deskling_paths_"))
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def test_user_data_dir_prefers_appdata(self) -> None:
        folder = self.make_temp_dir()
        old = os.environ.get("APPDATA")
        os.environ["APPDATA"] = str(folder)
        self.addCleanup(self._restore_env, "APPDATA", old)
        chosen = paths._user_data_dir()
        self.assertEqual(chosen, folder / "Deskling")
        self.assertTrue(chosen.is_dir())

    def test_frozen_characters_are_seeded_from_the_bundle(self) -> None:
        folder = self.make_temp_dir()
        old = (paths.FROZEN, paths.CHARACTERS_DIR, paths.BUNDLED_CHARACTERS_DIR)
        paths.FROZEN = True
        paths.CHARACTERS_DIR = folder / "characters"
        paths.BUNDLED_CHARACTERS_DIR = ROOT / "characters"
        try:
            seeded = paths.ensure_characters_dir()
            self.assertEqual(seeded, folder / "characters")
            self.assertTrue((seeded / "azhai" / "config.json").is_file())
            # A second call must not wipe or re-copy anything.
            marker = seeded / "azhai" / "edited.txt"
            marker.write_text("keep me", encoding="utf-8")
            paths.ensure_characters_dir()
            self.assertTrue(marker.is_file())
        finally:
            paths.FROZEN, paths.CHARACTERS_DIR, paths.BUNDLED_CHARACTERS_DIR = old

    def test_non_frozen_characters_are_used_directly(self) -> None:
        folder = self.make_temp_dir()
        old = (paths.FROZEN, paths.CHARACTERS_DIR, paths.BUNDLED_CHARACTERS_DIR)
        paths.FROZEN = False
        paths.CHARACTERS_DIR = folder / "characters"
        paths.BUNDLED_CHARACTERS_DIR = ROOT / "characters"
        try:
            paths.ensure_characters_dir()
            self.assertEqual(list((folder / "characters").iterdir()), [])
        finally:
            paths.FROZEN, paths.CHARACTERS_DIR, paths.BUNDLED_CHARACTERS_DIR = old

    @staticmethod
    def _restore_env(name: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
