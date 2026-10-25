"""Tests for the one-image custom character importer (offscreen, no desktop)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QApplication

from petapp.importer import create_character


class ImporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="deskling_import_"))
        self.addCleanup(lambda: shutil.rmtree(self.folder, True))
        self.characters = self.folder / "characters"
        self.characters.mkdir()
        self.sources = self.folder / "sources"
        self.sources.mkdir()
        # Keep importer tests deterministic on machines that happen to have
        # rembg/OpenCV installed; the optional paths have dedicated mocks.
        for target in (
            "petapp.packager.vision.rembg_available",
            "petapp.packager.vision.rembg_ready",
            "petapp.packager.vision.opencv_available",
        ):
            patcher = mock.patch(target, return_value=False)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_person(self, name: str, *, transparent: bool = False, striped: bool = False) -> Path:
        path = self.sources / name
        image = QImage(480, 720, QImage.Format.Format_ARGB32)
        if transparent:
            image.fill(Qt.GlobalColor.transparent)
        else:
            image.fill(QColor("#C9D8E8"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if striped:
            for i in range(20):
                painter.fillRect(0, i * 36, 480, 36, QColor(170 + i * 4, 115 + i * 5, 80 + i * 3))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#4A6FA5"))
        painter.drawRoundedRect(QRectF(120, 340, 240, 300), 30, 30)
        painter.setBrush(QColor("#F2C6A4"))
        painter.drawEllipse(QRectF(150, 120, 180, 210))
        painter.setBrush(QColor("#3E3457"))
        painter.drawEllipse(QRectF(135, 80, 210, 140))
        painter.setBrush(QColor("#3E3457"))
        painter.drawEllipse(QRectF(185, 195, 24, 28))
        painter.drawEllipse(QRectF(270, 195, 24, 28))
        painter.setPen(QPen(QColor("#B34A4A"), 6))
        painter.drawArc(QRectF(210, 245, 60, 40), 200 * 16, 140 * 16)
        painter.setBrush(QColor("#F2C6A4"))
        painter.drawRoundedRect(QRectF(150, 500, 70, 150), 25, 25)
        painter.drawRoundedRect(QRectF(260, 500, 70, 150), 25, 25)
        painter.end()
        self.assertTrue(image.save(str(path), "PNG"))
        return path

    def test_plain_background_is_keyed_out_into_a_character(self) -> None:
        source = self.make_person("anime_stand.png")
        character = create_character(source, self.characters)
        self.assertTrue((character.folder / "body.png").is_file())
        self.assertTrue((character.folder / "body_full.png").is_file())
        self.assertTrue((character.folder / "head.png").is_file())
        self.assertTrue((character.folder / "config.json").is_file())
        self.assertFalse(character.rig_enabled)
        self.assertEqual(
            {"normal"},
            set(character.expressions),
            "没有人工表情切片时只能保留原始 head.png，禁止自动画假五官",
        )
        self.assertFalse(
            (character.folder / "heads").exists(),
            "导入流程不应再生成 blink/angry/sleep 假表情图层",
        )
        self.assertFalse(character.bust_mode, "高挑立绘应该能自己溜达")
        self.assertRegex(character.accent, r"^#[0-9A-Fa-f]{6}$")
        for value in (*character.head_rect, *character.body_rect, *character.mouth):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
        self.assertGreater(character.pivot("head")[1], 0.2, "应自动算出颈部旋转锚点")
        self.assertLess(character.pivot("head")[1], 0.8)
        self.assertAlmostEqual(
            character.head_rect[1] + character.head_rect[3],
            character.pivot("head")[1],
            delta=0.02,
            msg="头部图层底边应落在颈部锚点附近",
        )
        self.assertLessEqual(character.body_rect[1], character.pivot("head")[1])
        body = QImage(str(character.folder / "body.png"))
        head = QImage(str(character.folder / "head.png"))
        self.assertFalse(body.isNull())
        self.assertEqual(body.size().width(), head.size().width())
        self.assertEqual(body.size().height(), head.size().height())
        self.assertEqual(body.size().width(), 720)
        self.assertEqual(body.size().height(), 1080)
        self.assertEqual(body.pixelColor(2, 2).alpha(), 0, "纯色背景应该被抠掉")
        self.assertGreater(body.pixelColor(360, 780).alpha(), 100, "人物身体要保留")
        self.assertGreater(character.motion.combo_threshold, 1)
        for name in ("head_top", "face", "mouth", "hand"):
            self.assertIn(name, character.mount_points, "导入角色也要拿到可用的锚点")
        self.assertNotIn("torso", character.mount_points)
        self.assertFalse(character.is_system)

    def test_import_emits_a_standard_skeleton_and_mesh(self) -> None:
        source = self.make_person("anime_stand.png")
        character = create_character(source, self.characters, name="骨骼同学")
        skeleton_file = character.folder / "skeleton.json"
        self.assertTrue(skeleton_file.is_file())
        self.assertIsNotNone(character.skeleton_file)
        document = json.loads(skeleton_file.read_text(encoding="utf-8"))
        self.assertEqual(character.skeleton, document)
        self.assertEqual(document["schema"], "deskling.2d-skeleton/1")
        self.assertEqual(document["root_bone"], "Root")
        nodes = {node["name"]: node for node in document["nodes"]}
        self.assertEqual(
            set(nodes),
            {"Root", "Torso", "Neck", "Head", "Hair", "Skirt"},
        )
        self.assertIsNone(nodes["Root"]["parent"])
        self.assertEqual(nodes["Torso"]["parent"], "Root")
        self.assertEqual(nodes["Neck"]["parent"], "Torso")
        self.assertEqual(nodes["Head"]["parent"], "Neck")
        self.assertEqual(nodes["Hair"]["parent"], "Head")
        self.assertEqual(nodes["Skirt"]["parent"], "Torso")
        self.assertGreater(len(document["outline"]), 8, "应提取到外轮廓")
        self.assertGreater(len(document["mesh"]["vertices"]), 8, "应生成骨骼蒙皮网格")
        self.assertGreater(len(document["mesh"]["triangles"]), 4)
        self.assertIn(document["mesh"]["method"], {"delaunay", "grid-fallback"})
        if document["mesh"]["method"] == "delaunay":
            self.assertGreater(
                len(document["mesh"]["triangles"]),
                100,
                "Delaunay 应生成数百个微型三角网格",
            )
        for vertex in document["mesh"]["vertices"]:
            self.assertTrue(vertex["weights"])
            self.assertIn(
                next(iter(vertex["weights"])),
                {"Head", "Neck", "Torso", "Hair", "Skirt"},
            )
        self.assertIn("Root/Torso/Neck/Head/Hair", document["godot"]["bone_paths"])
        self.assertIn("Root/Torso/Skirt", document["godot"]["bone_paths"])

    def test_import_metadata_name_subtitle_and_posture(self) -> None:
        source = self.make_person("IMG_2048.png")
        character = create_character(
            source,
            self.characters,
            name="小夏",
            subtitle="图书馆常驻NPC",
            posture="sit",
        )
        self.assertEqual(character.name, "小夏", "不能再用图片文件名命名")
        self.assertEqual(character.subtitle, "图书馆常驻NPC")
        self.assertTrue(character.bust_mode)
        self.assertEqual(character.posture, "sit")
        self.assertFalse(character.is_system)
        config = json.loads((character.folder / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["name"], "小夏")
        self.assertEqual(config["subtitle"], "图书馆常驻NPC")
        self.assertTrue(config["bust_mode"])
        self.assertEqual(config["posture"], "sit")

    def test_import_requires_a_name_when_one_is_supplied(self) -> None:
        source = self.make_person("blank_name.png")
        with self.assertRaises(ValueError):
            create_character(source, self.characters, name="   ")

    def test_transparent_png_keeps_alpha_and_sits_on_the_canvas_floor(self) -> None:
        source = self.make_person("sticker.png", transparent=True)
        character = create_character(source, self.characters)
        body = QImage(str(character.folder / "body.png"))
        self.assertEqual(body.pixelColor(2, 2).alpha(), 0)
        # Find the lowest opaque row; it should be near the bottom margin.
        lowest = 0
        for y in range(body.height() - 1, -1, -1):
            row_opaque = any(
                body.pixelColor(x, y).alpha() > 20
                for x in range(0, body.width(), 24)
            )
            if row_opaque:
                lowest = y
                break
        self.assertGreater(lowest, body.height() * 0.9, "角色应该落在画布底部")

    def test_busy_background_falls_back_to_a_paper_sticker(self) -> None:
        source = self.make_person("busy_photo.png", striped=True)
        character = create_character(source, self.characters)
        self.assertTrue(character.bust_mode, "复杂背景会退化成固定站立的照片贴纸")
        body = QImage(str(character.folder / "body.png"))
        paper_pixels = 0
        for y in range(0, body.height(), 6):
            for x in range(0, body.width(), 6):
                colour = body.pixelColor(x, y)
                if colour.alpha() > 100 and min(colour.red(), colour.green(), colour.blue()) > 225:
                    paper_pixels += 1
        self.assertGreater(paper_pixels, 30, "贴纸应该有白色纸边")

    def test_names_and_slugs_are_unique(self) -> None:
        source = self.make_person("classmate.png")
        first = create_character(source, self.characters, name="同学")
        second = create_character(
            source,
            self.characters,
            name="同学",
            existing_slugs={first.slug},
            existing_names={first.name},
        )
        self.assertNotEqual(first.slug, second.slug)
        self.assertNotEqual(first.name, second.name)
        self.assertTrue((self.characters / first.slug / "config.json").is_file())
        self.assertTrue((self.characters / second.slug / "config.json").is_file())
        self.assertTrue(second.slug.startswith("char_"), "重名导入应分配独立 ID")

    def test_generic_image_name_never_overwrites_images_folder(self) -> None:
        source = self.make_person("images.png")
        first = create_character(source, self.characters, name="images")
        self.assertNotEqual(first.slug, "images", "严禁复用默认 images 目录")
        self.assertTrue(first.slug.startswith("char_"))
        self.assertTrue((self.characters / "char_001").is_dir())
        second = create_character(
            source,
            self.characters,
            name="images",
            existing_slugs={first.slug},
            existing_names={first.name},
        )
        self.assertNotEqual(first.slug, second.slug)
        self.assertTrue((self.characters / "char_001").is_dir())
        self.assertTrue((self.characters / "char_002").is_dir())
        self.assertTrue((self.characters / "char_001" / "body.png").is_file())
        self.assertTrue((self.characters / "char_002" / "body.png").is_file())

    def test_imported_character_has_a_face_centred_avatar(self) -> None:
        source = self.make_person("avatar_person.png")
        character = create_character(source, self.characters, name="头像同学")
        self.assertIsNotNone(character.avatar_path)
        assert character.avatar_path is not None
        self.assertTrue(character.avatar_path.is_file())
        self.assertEqual(character.avatar_path.name, "avatar.png")
        avatar = QImage(str(character.avatar_path))
        self.assertEqual(avatar.width(), 256)
        self.assertEqual(avatar.height(), 256)
        self.assertGreater(
            avatar.pixelColor(128, 128).alpha(),
            0,
            "头像中心应落在人物脸部而不是左上角背景",
        )
        config = json.loads(
            (character.folder / "config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["avatar"], "avatar.png")
        self.assertIn(config["cutout"], {"alpha", "rembg", "flood-fill", "sticker"})

    def test_rembg_path_is_used_when_available(self) -> None:
        from petapp import vision

        source = self.make_person("rembg_person.png")
        cutout = QImage(480, 720, QImage.Format.Format_ARGB32)
        cutout.fill(Qt.GlobalColor.transparent)
        painter = QPainter(cutout)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#F2C6A4"))
        painter.drawEllipse(QRectF(140, 80, 200, 240))
        painter.setBrush(QColor("#4A6FA5"))
        painter.drawRoundedRect(QRectF(120, 300, 240, 380), 24, 24)
        painter.end()
        with mock.patch.object(vision, "rembg_available", return_value=True), \
             mock.patch.object(vision, "remove_background", return_value=cutout):
            character = create_character(
                source,
                self.characters,
                name="AI抠图同学",
                ai_cutout=True,
            )
        self.assertEqual(character.cutout_method, "rembg")

    def test_grabcut_fallback_handles_complex_photos(self) -> None:
        from petapp import vision

        source = self.make_person("door_photo.png", striped=True)
        cutout = QImage(480, 720, QImage.Format.Format_ARGB32)
        cutout.fill(Qt.GlobalColor.transparent)
        painter = QPainter(cutout)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#F2C6A4"))
        painter.drawEllipse(QRectF(140, 100, 200, 220))
        painter.setBrush(QColor("#4A6FA5"))
        painter.drawRoundedRect(QRectF(120, 320, 240, 360), 24, 24)
        painter.end()
        with mock.patch.object(vision, "rembg_ready", return_value=False), \
             mock.patch.object(vision, "remove_background", return_value=None), \
             mock.patch.object(vision, "grabcut_foreground", return_value=cutout):
            character = create_character(
                source,
                self.characters,
                name="GrabCut同学",
                ai_cutout=True,
            )
        self.assertEqual(character.cutout_method, "grabcut")

    def test_big_head_option_enlarges_face_and_updates_anchor(self) -> None:
        source = self.make_person("person.png")
        normal = create_character(source, self.characters, name="普通比例")
        big = create_character(
            source,
            self.characters,
            name="大头比例",
            big_head=True,
            head_scale=1.4,
        )
        self.assertFalse(normal.big_head)
        self.assertTrue(big.big_head)
        self.assertAlmostEqual(big.head_scale, 1.4)
        self.assertGreater(
            big.head_rect[3],
            normal.head_rect[3] * 1.25,
            "大头构图应该显著放大头部区域",
        )
        self.assertNotAlmostEqual(big.mouth[1], normal.mouth[1], places=3)
        self.assertIn("big_head", big.raw)
        self.assertTrue(big.raw["big_head"])
        self.assertAlmostEqual(big.raw["head_scale"], 1.4)
        body = QImage(str(big.folder / "body_full.png"))
        self.assertEqual(body.width(), 720)
        self.assertEqual(body.height(), 1080)

    def test_busy_photo_auto_enables_big_head(self) -> None:
        source = self.make_person("busy_photo.png", striped=True)
        character = create_character(source, self.characters, name="照片大头")
        self.assertTrue(character.bust_mode)
        self.assertTrue(character.big_head)
        self.assertAlmostEqual(character.head_scale, 1.4)

    def test_tiny_image_is_rejected(self) -> None:
        path = self.sources / "tiny.png"
        image = QImage(10, 10, QImage.Format.Format_ARGB32)
        image.fill(QColor("#FFFFFF"))
        self.assertTrue(image.save(str(path), "PNG"))
        with self.assertRaises(ValueError):
            create_character(path, self.characters)


if __name__ == "__main__":
    unittest.main()
