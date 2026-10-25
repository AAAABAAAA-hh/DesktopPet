from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from petapp.config import RIG_PART_NAMES, Catalog, Settings, load_character, load_characters

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        DATA.mkdir(exist_ok=True)

    def make_temp_dir(self) -> Path:
        folder = DATA / f"_test_config_{uuid.uuid4().hex[:8]}"
        folder.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def test_all_characters_and_layers(self) -> None:
        characters = load_characters(ROOT / "characters")
        self.assertGreaterEqual(len(characters), 3)
        for character in characters:
            self.assertTrue(character.name)
            self.assertIsNotNone(character.layer_path("body"))
            self.assertTrue(character.expression_path("normal"))
            self.assertIn("poke", character.lines)
            self.assertGreater(character.scale, 0)

    def test_bundled_characters_have_articulated_layers(self) -> None:
        characters = load_characters(ROOT / "characters")
        self.assertGreaterEqual(len(characters), 3)
        for character in characters:
            # Elaina uses the new single-body + separate head pipeline, and
            # user-imported characters (e.g. ``images``) may not ship the five
            # rig parts.  The four original paper dolls still exercise it.
            if character.slug not in {"azhai", "xiaoman", "laowang", "linlin"}:
                self.assertFalse(character.rig_enabled, character.slug)
                continue
            self.assertTrue(character.rig_enabled, character.slug)
            self.assertEqual(set(character.parts), set(RIG_PART_NAMES))
            for part in character.parts.values():
                self.assertTrue(part.is_file(), part)
            for joint in ("torso", "arm_left", "arm_right", "leg_left", "leg_right", "head"):
                x, y = character.pivot(joint)
                self.assertGreaterEqual(x, 0.0)
                self.assertLessEqual(x, 1.0)
                self.assertGreaterEqual(y, 0.0)
                self.assertLessEqual(y, 1.0)

    def test_catalog(self) -> None:
        catalog = Catalog.load(ROOT / "assets" / "items")
        self.assertGreaterEqual(len(catalog.foods), 3)
        self.assertGreaterEqual(len(catalog.items), 5)
        self.assertIsNotNone(catalog.item("sunglasses"))
        self.assertIsNotNone(catalog.item("witch_hat"))
        self.assertIsNotNone(catalog.item("milktea_hold"))
        self.assertIsNone(catalog.item("dress"), "躯干服装已从装扮系统移除")
        self.assertIsNotNone(catalog.food("drumstick"))
        self.assertIsNotNone(catalog.prop("book"))

    def test_catalog_items_have_socket_metadata(self) -> None:
        catalog = Catalog.load(ROOT / "assets" / "items")
        hat = catalog.item("witch_hat")
        self.assertIsNotNone(hat)
        self.assertEqual(hat.mount, "head_top")
        self.assertGreater(hat.fit, 0.0)
        self.assertEqual(len(hat.offset), 2)
        self.assertIsNone(catalog.item("dress"))
        for item in catalog.items.values():
            self.assertIn(item.mount, {"head_top", "face", "hand"})
            self.assertTrue(item.is_accessory)
            self.assertNotIn(item.mount, {"torso", "body"})
        self.assertIn("hand", {item.mount for item in catalog.items.values()})
        food = catalog.food("drumstick")
        self.assertIsNotNone(food)
        self.assertEqual(food.mount, "mouth")
        self.assertGreater(food.fit, 0.0)
        book = catalog.prop("book")
        self.assertIsNotNone(book)
        self.assertEqual(book.mount, "hand")

    def test_legacy_torso_outfit_entries_are_skipped(self) -> None:
        folder = self.make_temp_dir()
        shutil.copyfile(ROOT / "assets" / "items" / "sunglasses.png", folder / "shades.png")
        (folder / "catalog.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "legacy_dress",
                            "name": "旧裙子",
                            "slot": "outfit",
                            "mount": "torso",
                            "file": "shades.png",
                        },
                        {
                            "id": "shades",
                            "name": "墨镜",
                            "slot": "face",
                            "mount": "face",
                            "file": "shades.png",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        catalog = Catalog.load(folder)
        self.assertIsNone(catalog.item("legacy_dress"))
        self.assertIsNotNone(catalog.item("shades"))
        self.assertTrue(catalog.item("shades").is_accessory)

    def test_every_character_covers_every_catalog_socket(self) -> None:
        catalog = Catalog.load(ROOT / "assets" / "items")
        for character in load_characters(ROOT / "characters"):
            for item in catalog.items.values():
                self.assertIn(item.mount, character.mount_points, item.id)
            for food in catalog.foods.values():
                self.assertIn(food.mount, character.mount_points, food.id)
            book = catalog.prop("book")
            self.assertIsNotNone(book)
            self.assertIn(book.mount, character.mount_points)

    def test_mount_points_default_and_override(self) -> None:
        folder = self.make_temp_dir() / "sockets"
        folder.mkdir()
        shutil.copyfile(ROOT / "characters" / "azhai" / "body.png", folder / "body.png")
        (folder / "config.json").write_text(
            json.dumps(
                {
                    "name": "锚点测试",
                    "slug": "socket_test",
                    "head_rect": [0.1, 0.05, 0.8, 0.4],
                    "body_rect": [0.2, 0.5, 0.6, 0.45],
                    "mouth": [0.52, 0.42],
                    "mount_points": {
                        "head_top": {"point": [0.5, 0.11], "width": 0.9},
                        "hand": [0.35, 0.66],
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        character = load_character(folder)
        self.assertAlmostEqual(character.mount_point("head_top").y, 0.11)
        self.assertAlmostEqual(character.mount_point("head_top").width, 0.9)
        self.assertAlmostEqual(character.mount_point("hand").x, 0.35)
        self.assertAlmostEqual(character.mount_point("mouth").x, 0.52)
        # A missing name still resolves to a usable socket instead of crashing.
        self.assertEqual(character.mount_point("typo").name, "face")
        self.assertNotIn("torso", character.mount_points)
        self.assertNotIn("body", character.mount_points)

    def test_elaina_witch_is_bundled(self) -> None:
        characters = {c.slug: c for c in load_characters(ROOT / "characters")}
        elaina = characters.get("elaina")
        self.assertIsNotNone(elaina)
        self.assertEqual(elaina.name, "伊蕾娜")
        # The new art already includes the hat; an extra wardrobe hat would
        # double it.  It is a single body layer plus an aligned head texture,
        # not the old five-part ragdoll rig.
        self.assertEqual(elaina.starting_accessories, ())
        self.assertFalse(elaina.rig_enabled)
        self.assertEqual(elaina.expression_path("normal").name, "head.png")
        self.assertTrue(elaina.face_static)
        self.assertFalse(elaina.has_costumes)
        self.assertEqual(set(elaina.expressions), {"normal"})
        self.assertFalse(
            (elaina.folder / "heads").exists(),
            "自动派生的 blink/angry/sleep 头部图层必须从磁盘删除",
        )
        self.assertEqual(elaina.layer_path("body").name, "body.png")
        self.assertTrue((elaina.folder / "body_full.png").is_file())
        self.assertAlmostEqual(elaina.motion.drag_tilt_max, 10.0)
        self.assertLessEqual(elaina.motion.drag_bob_speed, 1.5)
        self.assertEqual(elaina.motion.drag_panic_expression, "normal")
        self.assertAlmostEqual(elaina.motion.fall_tilt, 10.0)
        self.assertIn("head_top", elaina.mount_points)
        self.assertNotIn("torso", elaina.mount_points)
        self.assertAlmostEqual(elaina.mount_point("head_top").width, 0.75)
        self.assertAlmostEqual(elaina.mount_point("mouth").x, elaina.mouth[0])
        self.assertAlmostEqual(elaina.rage_threshold, 99.5)
        self.assertTrue(elaina.is_system)
        self.assertFalse(elaina.deletable)

    def test_system_initial_characters_are_locked(self) -> None:
        from petapp.config import SYSTEM_CHARACTER_SLUGS, is_system_character

        self.assertEqual(
            set(SYSTEM_CHARACTER_SLUGS),
            {"xiaoman", "laowang", "linlin", "elaina"},
        )
        characters = {c.slug: c for c in load_characters(ROOT / "characters")}
        for slug in SYSTEM_CHARACTER_SLUGS:
            self.assertTrue(characters[slug].is_system, slug)
            self.assertFalse(characters[slug].deletable, slug)
            self.assertTrue(is_system_character(slug))
        self.assertFalse(is_system_character("azhai"))

    def test_motion_profile_comes_from_config(self) -> None:
        folder = self.make_temp_dir() / "motion_character"
        folder.mkdir()
        shutil.copyfile(ROOT / "characters" / "azhai" / "body.png", folder / "body.png")
        (folder / "config.json").write_text(
            json.dumps(
                {
                    "name": "动作测试",
                    "slug": "motion_test",
                    "motion": {
                        "drag": {
                            "tilt_gain": 0.008,
                            "tilt_max": 9.0,
                            "bob_speed": 1.35,
                            "bob": 1.8,
                            "panic_expression": "blink",
                        },
                        "combo": {"threshold": 4, "window": 1.2},
                    },
                    "rage_threshold": 80,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        character = load_character(folder)
        self.assertAlmostEqual(character.motion.drag_tilt_gain, 0.008)
        self.assertAlmostEqual(character.motion.drag_tilt_max, 9.0)
        self.assertAlmostEqual(character.motion.drag_bob_speed, 1.35)
        self.assertAlmostEqual(character.motion.drag_bob, 1.8)
        self.assertEqual(character.motion.drag_panic_expression, "blink")
        self.assertEqual(character.motion.combo_threshold, 4)
        self.assertAlmostEqual(character.motion.combo_window, 1.2)
        self.assertAlmostEqual(character.rage_threshold, 80.0)
        # Omitted fields keep the shared defaults instead of becoming zero.
        self.assertAlmostEqual(character.motion.tap_width, 0.05)
        self.assertAlmostEqual(character.motion.combo_angry_seconds, 2.2)

    def test_settings_roundtrip(self) -> None:
        tmp = self.make_temp_dir()
        path = tmp / "settings.json"
        settings = Settings(
            sound_enabled=False,
            mischief_enabled=False,
            auto_watch=False,
            max_pets=3,
            last_character="xiaoman",
            first_run=False,
            scales={"azhai": 1.25, "linlin": 2.8},
        )
        settings.save(path)
        restored = Settings.load(path)
        self.assertFalse(restored.sound_enabled)
        self.assertFalse(restored.mischief_enabled)
        self.assertFalse(restored.auto_watch)
        self.assertEqual(restored.max_pets, 3)
        self.assertEqual(restored.last_character, "xiaoman")
        self.assertFalse(restored.first_run)
        self.assertAlmostEqual(restored.scales["azhai"], 1.25)
        self.assertEqual(restored.scale_for("azhai", 0.88), 1.25)
        self.assertEqual(restored.scale_for("linlin", 0.82), 2.0, "保存的尺寸要夹在 20%~200%")
        self.assertEqual(restored.scale_for("laowang", 0.9), 0.4, "没有保存过尺寸时默认 40%")

    def test_single_canvas_body_only_character(self) -> None:
        folder = self.make_temp_dir() / "solo"
        folder.mkdir()
        source = ROOT / "characters" / "azhai" / "body.png"
        shutil.copyfile(source, folder / "body.png")
        (folder / "config.json").write_text(
            json.dumps(
                {
                    "name": "单图同学",
                    "slug": "solo",
                    "canvas": [360, 540],
                    "head_rect": [0.14, 0.02, 0.72, 0.46],
                    "body_rect": [0.15, 0.48, 0.7, 0.5],
                    "bust_mode": True,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        character = load_character(folder)
        self.assertEqual(character.name, "单图同学")
        self.assertIsNotNone(character.layer_path("body"))
        self.assertEqual(character.expressions, {})
        self.assertTrue(character.bust_mode)
        self.assertFalse(character.rig_enabled, "没有 parts/ 时应该回退到整张身体图")
        # Old character folders without mount_points still get usable sockets.
        for name in ("head_top", "face", "mouth", "hand"):
            self.assertIn(name, character.mount_points)
            self.assertGreater(character.mount_point(name).width, 0.0)
        self.assertNotIn("torso", character.mount_points)
        self.assertNotIn("body", character.mount_points)

    def test_pose_textures_fall_back_then_auto_discover(self) -> None:
        folder = self.make_temp_dir() / "poses"
        folder.mkdir()
        body = folder / "body.png"
        shutil.copyfile(ROOT / "characters" / "azhai" / "body.png", body)
        (folder / "config.json").write_text(
            json.dumps({"name": "姿态测试", "slug": "pose_test"}, ensure_ascii=False),
            encoding="utf-8",
        )
        character = load_character(folder)
        for pose in ("idle", "sit", "walk_left", "walk_right", "drag"):
            self.assertEqual(character.pose_path(pose), body, pose)
            self.assertFalse(character.has_dedicated_pose(pose), pose)

        # Adding conventional files lights up the matching pose automatically.
        shutil.copyfile(body, folder / "sit.png")
        character = load_character(folder)
        self.assertEqual(character.pose_path("sit").name, "sit.png")
        self.assertTrue(character.has_dedicated_pose("sit"))
        self.assertEqual(character.pose_path("idle"), body, "未提供的姿态继续回退")

        shutil.copyfile(body, folder / "walk.png")
        character = load_character(folder)
        self.assertEqual(character.pose_path("walk_left").name, "walk.png")
        self.assertEqual(character.pose_path("walk_right").name, "walk.png")
        self.assertTrue(character.has_dedicated_pose("walk_left"))

        shutil.copyfile(body, folder / "walk_left.png")
        character = load_character(folder)
        self.assertEqual(character.pose_path("walk_left").name, "walk_left.png")
        self.assertEqual(character.pose_path("walk_right").name, "walk.png")

        shutil.copyfile(body, folder / "drag.png")
        character = load_character(folder)
        self.assertEqual(character.pose_path("drag").name, "drag.png")
        self.assertTrue(character.has_dedicated_pose("drag"))

    def test_pose_config_can_point_at_existing_files(self) -> None:
        folder = self.make_temp_dir() / "poses_config"
        folder.mkdir()
        shutil.copyfile(ROOT / "characters" / "azhai" / "body.png", folder / "body.png")
        shutil.copyfile(ROOT / "characters" / "azhai" / "body.png", folder / "seated.png")
        (folder / "config.json").write_text(
            json.dumps(
                {
                    "name": "配置姿态",
                    "slug": "pose_config",
                    "poses": {"sit": "seated.png", "walk_right": "missing.png"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        character = load_character(folder)
        self.assertEqual(character.pose_path("sit").name, "seated.png")
        self.assertTrue(character.has_dedicated_pose("sit"))
        self.assertEqual(character.pose_path("walk_right"), folder / "body.png")

    def test_bad_config_is_rejected(self) -> None:
        folder = self.make_temp_dir() / "broken"
        folder.mkdir()
        (folder / "config.json").write_text("{not-json", encoding="utf-8")
        with self.assertRaises(Exception):
            load_character(folder)


if __name__ == "__main__":
    unittest.main()
