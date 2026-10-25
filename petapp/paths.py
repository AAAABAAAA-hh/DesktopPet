"""Filesystem locations used by Deskling.

Two very different kinds of files are involved:

* **Bundled resources** (``assets/``, ``characters/``) are read-only and, in a
  PyInstaller build, live inside the exe bundle.  They are only ever read.
* **Writable state** (settings, logs, imported faces, an editable copy of the
  characters) must live in a normal user folder.  In a frozen build that is
  ``%APPDATA%\\Deskling`` (with fallbacks), never the exe folder or the
  temporary extraction directory.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

#: True inside a PyInstaller build: read-only resources live in the bundle,
#: writable state must go somewhere that survives restarts.
FROZEN = bool(getattr(sys, "frozen", False))


def _resource_root() -> Path:
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


APP_ROOT = _resource_root()
PACKAGE_DIR = APP_ROOT / "petapp"
ASSETS_DIR = APP_ROOT / "assets"
ITEMS_DIR = ASSETS_DIR / "items"
SOUNDS_DIR = ASSETS_DIR / "sounds"
SCREENSHOTS_DIR = APP_ROOT / "screenshots"
#: Characters shipped inside the exe / repository.
BUNDLED_CHARACTERS_DIR = APP_ROOT / "characters"

WRITE_PROBE = ".deskling_write_test"


def _is_writable(directory: Path) -> bool:
    """Create the folder and prove it accepts a file, then clean up."""

    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / WRITE_PROBE
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _user_data_dir() -> Path:
    """Pick a writable per-user folder, in order of preference."""

    candidates: list[Path] = []
    for variable in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "Deskling")
    documents = Path.home() / "Documents"
    if documents.is_dir():
        candidates.append(documents / "Deskling")
    candidates.append(Path(sys.executable).resolve().parent / "DesklingData")
    candidates.append(Path(tempfile.gettempdir()) / "Deskling")
    candidates.append(Path.home() / "Deskling")

    for candidate in candidates:
        if _is_writable(candidate):
            return candidate
    # Last resort: the working directory; better than crashing on startup.
    return Path.cwd()


if FROZEN:
    DATA_DIR = _user_data_dir()
    #: Editable copy of the characters, seeded from the bundle on first run.
    CHARACTERS_DIR = DATA_DIR / "characters"
else:
    DATA_DIR = APP_ROOT / "data"
    CHARACTERS_DIR = BUNDLED_CHARACTERS_DIR

ICON_FILE = ASSETS_DIR / "icon.png"
CATALOG_FILE = ITEMS_DIR / "catalog.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
LOG_FILE = DATA_DIR / "deskling.log"
LOCK_FILE = DATA_DIR / "deskling.lock"
STATE_FILE = DATA_DIR / "session.json"



def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def ensure_characters_dir() -> Path:
    """Return the editable characters folder, seeding it on first run.

    Inside an exe the bundled characters are read-only (and, for a one-file
    build, disappear when the app exits), so they are copied once into the
    user data folder.  Everything afterwards — adding a classmate, replacing
    PNGs, importing a face — happens in that writable copy.
    """

    directory = CHARACTERS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    if not FROZEN or not BUNDLED_CHARACTERS_DIR.is_dir():
        return directory
    try:
        entries = list(BUNDLED_CHARACTERS_DIR.iterdir())
    except OSError:
        return directory
    for source in entries:
        if not source.is_dir():
            continue
        target = directory / source.name
        if target.exists():
            continue
        try:
            shutil.copytree(source, target)
        except OSError:
            log.warning("复制角色素材失败：%s", source, exc_info=True)
    return directory
