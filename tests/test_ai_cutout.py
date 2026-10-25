"""Integration test for the real rembg cutout path.

Skipped only when the optional local model is absent; when it is present this
proves the importer really strips a busy background instead of producing a
rectangular paper sticker.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from petapp import vision
from petapp.importer import create_character


class RealRembgCutoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="deskling_ai_"))
        self.addCleanup(lambda: shutil.rmtree(self.folder, True))
        self.characters = self.folder / "characters"
        self.characters.mkdir()
        source = self.folder / "door_photo.png"
        image = QImage(640, 900, QImage.Format.Format_ARGB32)
        image.fill(QColor("#D8E0E8"))
        painter = QPainter(image)
        # Door frame + wall clutter.
        painter.fillRect(20, 20, 600, 860, QColor("#8A5A3C"))
        painter.fillRect(60, 60, 520, 770, QColor("#C99A6A"))
        for i in range(0, 640, 28):
            painter.fillRect(i, 0, 12, 900, QColor(90 + i % 80, 70, 55))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#F2C6A4"))
        painter.drawEllipse(QRectF(220, 150, 200, 220))
        painter.setBrush(QColor("#3E3457"))
        painter.drawEllipse(QRectF(215, 110, 210, 130))
        painter.setBrush(QColor("#4A6FA5"))
        painter.drawRoundedRect(QRectF(200, 370, 240, 330), 24, 24)
        painter.end()
        image.save(str(source))
        self.source = source

    @unittest.skipUnless(
        vision.rembg_ready(),
        "rembg/u2netp model is not installed",
    )
    def test_importer_uses_rembg_and_never_stickers(self) -> None:
        character = create_character(self.source, self.characters, name="小夏")
        self.assertEqual(character.cutout_method, "rembg")
        self.assertFalse(character.bust_mode, "AI 去底后不应出现长方形贴纸")
        body = QImage(str(character.folder / "body.png"))
        self.assertFalse(body.isNull())
        self.assertLess(body.pixelColor(2, 2).alpha(), 20)
        self.assertLess(body.pixelColor(body.width() - 3, 2).alpha(), 20)
        self.assertIsNotNone(character.avatar_path)
        avatar = QImage(str(character.avatar_path))
        self.assertEqual((avatar.width(), avatar.height()), (256, 256))
        config = json.loads(
            (character.folder / "config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["cutout"], "rembg")
        self.assertEqual(config["avatar"], "avatar.png")


if __name__ == "__main__":
    unittest.main()
