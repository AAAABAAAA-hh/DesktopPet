"""Tests for the optional Godot 4 bridge (does not launch an engine)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import bridge as bridge_module
from engine.bridge import GodotBridge, find_godot


class GodotBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="deskling_godot_"))
        self.addCleanup(lambda: shutil.rmtree(self.folder, True))
        self.character = self.folder / "character"
        self.character.mkdir()
        (self.character / "body.png").write_bytes(b"not a real png")
        (self.character / "skeleton.json").write_text("{}", encoding="utf-8")
        self.state = self.folder / "state.json"

    def test_missing_godot_degrades_cleanly(self) -> None:
        with mock.patch("engine.bridge.find_godot", return_value=None):
            bridge = GodotBridge(self.character, state_file=self.state)
        self.assertFalse(bridge.available)
        self.assertFalse(bridge.running)
        self.assertFalse(bridge.start())
        self.assertEqual(bridge.command, [])
        bridge.stop()

    def test_state_file_protocol_updates_atomically(self) -> None:
        with mock.patch("engine.bridge.find_godot", return_value=Path("fake-godot")):
            bridge = GodotBridge(self.character, state_file=self.state)
        self.assertTrue(bridge.available)
        self.assertTrue(bridge.update(x=12, y=34, state="drag", vx=900, pose="drag"))
        payload = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(payload["x"], 12)
        self.assertEqual(payload["y"], 34)
        self.assertEqual(payload["state"], "drag")
        self.assertEqual(payload["vx"], 900)
        self.assertEqual(payload["pose"], "drag")
        self.assertFalse(payload["quit"])

    def test_command_contains_project_and_character(self) -> None:
        with mock.patch("engine.bridge.find_godot", return_value=Path("fake-godot")):
            bridge = GodotBridge(self.character, state_file=self.state)
        command = bridge.command
        self.assertIn("--path", command)
        self.assertIn("--character", command)
        self.assertIn("--state", command)
        self.assertIn(str(bridge_module.PROJECT_DIR), command)
        self.assertIn(str(self.character.resolve()), command)

    def test_project_files_exist(self) -> None:
        project = bridge_module.PROJECT_DIR
        self.assertTrue((project / "project.godot").is_file())
        self.assertTrue((project / "main.tscn").is_file())
        self.assertTrue((project / "main.gd").is_file())
        text = (project / "main.gd").read_text(encoding="utf-8")
        self.assertIn("skeleton.json", text)
        self.assertIn("Bone2D", text)
        self.assertIn("Torso", text)
        self.assertIn("Neck", text)
        self.assertIn("Head", text)

    def test_find_godot_returns_only_existing_files(self) -> None:
        result = find_godot(self.folder / "missing-godot")
        self.assertTrue(result is None or result.is_file())


if __name__ == "__main__":
    unittest.main()
