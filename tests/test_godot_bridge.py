"""Tests for the optional Godot 4 bridge and generated runtime project."""

from __future__ import annotations

import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from petapp import godot_bridge
from petapp.godot_bridge import GodotBridge


class GodotBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="deskling_godot_runtime_"))
        self.addCleanup(lambda: shutil.rmtree(self.folder, True))
        self.character = self.folder / "character"
        self.character.mkdir()
        (self.character / "skeleton.json").write_text("{}", encoding="utf-8")
        self.state = self.folder / "state.json"

    def test_runtime_project_has_transparent_borderless_settings(self) -> None:
        runtime = godot_bridge.ensure_runtime()
        self.assertEqual(runtime, godot_bridge.RUNTIME_DIR)
        project = (runtime / "project.godot").read_text(encoding="utf-8")
        for setting in (
            "window/size/borderless=true",
            "window/size/transparent=true",
            "window/per_pixel_transparency/allowed=true",
            "window/size/always_on_top=true",
        ):
            self.assertIn(setting, project)
        self.assertTrue((runtime / "pet_renderer.gd").is_file())
        self.assertTrue((runtime / "pet_renderer.tscn").is_file())
        script = (runtime / "pet_renderer.gd").read_text(encoding="utf-8")
        self.assertIn("skeleton.json", script)
        self.assertIn("Skeleton2D", script)
        self.assertIn("Bone2D", script)
        self.assertIn("Polygon2D", script)
        self.assertIn("get_available_packet_count", script)

    def test_missing_godot_degrades_cleanly(self) -> None:
        with mock.patch("petapp.godot_bridge.find_godot", return_value=None):
            bridge = GodotBridge(self.character, state_file=self.state)
        self.assertFalse(bridge.available)
        self.assertFalse(bridge.running)
        self.assertFalse(bridge.start())
        bridge.stop()

    def test_command_and_state_protocol(self) -> None:
        with mock.patch("petapp.godot_bridge.find_godot", return_value=Path("fake-godot")):
            bridge = GodotBridge(self.character, state_file=self.state)
        self.assertTrue(bridge.available)
        command = bridge.command
        self.assertIn("--path", command)
        self.assertIn(str(godot_bridge.RUNTIME_DIR), command)
        self.assertIn("--character", command)
        self.assertIn("--port", command)
        self.assertIn(str(bridge.port), command)
        self.assertTrue(bridge.update(x=9, y=10, state="walk", pose="walk_left", vx=30))
        payload = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(payload["x"], 9)
        self.assertEqual(payload["pose"], "walk_left")
        self.assertFalse(payload["quit"])

    def test_udp_packet_is_loopback_json(self) -> None:
        with mock.patch("petapp.godot_bridge.find_godot", return_value=Path("fake-godot")):
            bridge = GodotBridge(self.character, state_file=self.state)
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            receiver.bind(("127.0.0.1", bridge.port))
            receiver.settimeout(1.0)
            self.assertTrue(bridge._send({"x": 1, "state": "drag"}))
            data, address = receiver.recvfrom(65535)
            payload = json.loads(data.decode("utf-8"))
            self.assertEqual(payload["x"], 1)
            self.assertEqual(address[0], "127.0.0.1")
        finally:
            receiver.close()
            bridge.stop()


if __name__ == "__main__":
    unittest.main()
