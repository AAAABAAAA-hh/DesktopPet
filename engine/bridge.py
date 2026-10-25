"""Python → Godot 4 render bridge.

The PyQt process stays authoritative: it owns the tray, menus, interaction and
the character model.  This bridge launches the tiny Godot project in
``engine/`` for per-pixel-transparent rendering and writes a small JSON state
file that the shell polls.  No network or remote service is involved.

Typical use::

    bridge = GodotBridge(character.folder)
    if bridge.available:
        bridge.start(width=288, height=432, x=1200, y=600)
        bridge.update(pose="walk_left", state="walk", vx=30, x=1190)
        bridge.stop()

CLI preview::

    python -m engine.bridge --character characters/elaina --duration 20
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
_STATE_NAME = "deskling_engine_state.json"


def _candidate_globs() -> list[str]:
    return [
        "Godot_v4*",
        "godot4*",
        "Godot*",
        "godot*",
    ]


def find_godot(explicit: str | Path | None = None) -> Path | None:
    """Locate a local Godot 4 executable without downloading anything."""

    values: list[str] = []
    if explicit:
        values.append(str(explicit))
    env = os.environ.get("GODOT_BIN") or os.environ.get("GODOT4_BIN")
    if env:
        values.append(env)
    for name in ("godot", "godot4", "Godot", "Godot4"):
        found = shutil.which(name)
        if found:
            values.append(found)

    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        Path(r"D:\software"),
        Path.home() / "Godot",
    ]
    for root in roots:
        if not str(root) or not root.is_dir():
            continue
        for pattern in _candidate_globs():
            try:
                values.extend(str(path) for path in root.glob(pattern))
            except OSError:
                continue

    for value in values:
        path = Path(value)
        if path.is_file():
            return path
        found = shutil.which(value)
        if found:
            return Path(found)
    return None


class GodotBridge:
    """Launch and drive the optional Godot render shell."""

    def __init__(
        self,
        character_dir: Path | str,
        *,
        godot_bin: str | Path | None = None,
        state_file: Path | str | None = None,
    ) -> None:
        self.character_dir = Path(character_dir)
        self.godot_bin = find_godot(godot_bin)
        self.state_file = Path(
            state_file
            or (Path(tempfile.gettempdir()) / f"{_STATE_NAME}.{os.getpid()}.{uuid.uuid4().hex[:8]}.json")
        )
        self.process: subprocess.Popen[bytes] | None = None
        self._state: dict[str, Any] = {
            "x": 0,
            "y": 0,
            "width": 288,
            "height": 432,
            "scale": 0.8,
            "state": "idle",
            "pose": "idle",
            "vx": 0.0,
            "quit": False,
        }

    @property
    def available(self) -> bool:
        return self.godot_bin is not None and self.character_dir.is_dir()

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def command(self) -> list[str]:
        if self.godot_bin is None:
            return []
        return [
            str(self.godot_bin),
            "--path",
            str(PROJECT_DIR),
            "--",
            "--character",
            str(self.character_dir.resolve()),
            "--state",
            str(self.state_file.resolve()),
        ]

    def update(self, **state: Any) -> bool:
        """Merge one state update and atomically publish it for Godot."""

        self._state.update(state)
        self._state["quit"] = False
        return self._write_state()

    def _write_state(self) -> bool:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_file.with_suffix(".tmp")
            payload = json.dumps(self._state, ensure_ascii=False)
            temporary.write_text(payload, encoding="utf-8")
            try:
                temporary.replace(self.state_file)
            except OSError:
                # Windows can briefly hold the target while Godot reads it.
                self.state_file.write_text(payload, encoding="utf-8")
            return True
        except OSError:
            return False

    def start(
        self,
        *,
        width: int = 288,
        height: int = 432,
        x: int = 0,
        y: int = 0,
        scale: float = 0.8,
    ) -> bool:
        if not self.available:
            return False
        if self.running:
            return True
        self._state.update(
            {
                "x": int(x),
                "y": int(y),
                "width": max(16, int(width)),
                "height": max(16, int(height)),
                "scale": float(scale),
                "quit": False,
            }
        )
        self._write_state()
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.process = subprocess.Popen(
                self.command,
                cwd=str(PROJECT_DIR),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError:
            self.process = None
            return False
        return True

    def stop(self, timeout: float = 2.0) -> None:
        if self.process is None:
            return
        try:
            self._state["quit"] = True
            self._write_state()
            self.process.wait(timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            try:
                self.process.terminate()
                self.process.wait(timeout=timeout)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    self.process.kill()
                except OSError:
                    pass
        finally:
            self.process = None
            try:
                self.state_file.unlink(missing_ok=True)
            except OSError:
                pass

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        try:
            self.stop(timeout=0.5)
        except Exception:
            pass


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the optional Godot 4 Deskling renderer")
    parser.add_argument("--character", type=Path, required=True)
    parser.add_argument("--godot", type=Path, default=None)
    parser.add_argument("--width", type=int, default=288)
    parser.add_argument("--height", type=int, default=432)
    parser.add_argument("--x", type=int, default=100)
    parser.add_argument("--y", type=int, default=100)
    parser.add_argument("--duration", type=float, default=0.0, help="0 = run until Ctrl+C")
    args = parser.parse_args(argv)
    bridge = GodotBridge(args.character, godot_bin=args.godot)
    if not bridge.available:
        print(
            "Godot 4 executable not found. Set GODOT_BIN or install Godot 4; "
            "the normal PyQt renderer remains available.",
            file=sys.stderr,
        )
        return 2
    if not bridge.start(width=args.width, height=args.height, x=args.x, y=args.y):
        print("Failed to launch Godot.", file=sys.stderr)
        return 3
    print(f"Godot renderer launched: pid={bridge.process.pid if bridge.process else '?'}")
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    try:
        while bridge.running and (deadline is None or time.monotonic() < deadline):
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
