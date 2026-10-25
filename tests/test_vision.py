"""Pure-geometry tests for optional vision helpers (no model downloads)."""

from __future__ import annotations

import unittest

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter

from petapp import vision


class VisionFallbackTests(unittest.TestCase):
    def test_face_centred_box_uses_detected_face(self) -> None:
        head = QRect(100, 80, 320, 360)
        face = QRect(190, 150, 90, 90)
        box = vision.face_centred_box(head, face, (1000, 1000))
        self.assertEqual(box.width(), box.height())
        self.assertTrue(box.contains(face.center()), "头像必须包含人脸中心")
        self.assertLess(box.left(), face.left())
        self.assertGreater(box.right(), face.right())
        self.assertNotEqual((box.left(), box.top()), (0, 0))

    def test_face_centred_box_falls_back_to_upper_head_not_corner(self) -> None:
        head = QRect(100, 80, 320, 360)
        box = vision.face_centred_box(head, None, (1000, 1000))
        self.assertEqual(box.width(), box.height())
        self.assertTrue(box.contains(260, 290), "没有检测器时也应聚焦头部中下部")
        self.assertGreater(box.left(), 0)
        self.assertGreater(box.center().y(), head.center().y())
        self.assertNotEqual((box.left(), box.top()), (0, 0))

    def test_optional_rembg_is_safe_when_missing(self) -> None:
        image = QImage(64, 64, QImage.Format.Format_ARGB32)
        image.fill(0)
        result = vision.remove_background(image)
        if vision.rembg_available():
            self.assertTrue(result is None or not result.isNull())
        else:
            self.assertIsNone(result)

    @unittest.skipUnless(
        vision.rembg_available() and vision.rembg_ready(),
        "rembg/u2netp model is not installed",
    )
    def test_rembg_strips_a_complex_photo_background(self) -> None:
        image = QImage(640, 720, QImage.Format.Format_ARGB32)
        image.fill(QColor("#DCE4EC"))
        painter = QPainter(image)
        # A busy, door-frame-like background.
        for i in range(0, 640, 32):
            painter.fillRect(i, 0, 16, 720, QColor(120 + i % 90, 90, 70))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#F2C6A4"))
        painter.drawEllipse(QRectF(220, 120, 200, 220))
        painter.setBrush(QColor("#4A6FA5"))
        painter.drawRoundedRect(QRectF(200, 340, 240, 340), 24, 24)
        painter.end()
        cutout = vision.remove_background(image)
        self.assertIsNotNone(cutout)
        self.assertFalse(cutout.isNull())
        self.assertLess(cutout.pixelColor(2, 2).alpha(), 40)
        self.assertGreater(cutout.pixelColor(320, 200).alpha(), 40)

    def test_optional_face_detector_returns_none_or_rect(self) -> None:
        image = QImage(320, 480, QImage.Format.Format_ARGB32)
        image.fill(0)
        result = vision.detect_face_box(image, QRect(40, 20, 240, 260))
        self.assertTrue(result is None or isinstance(result, QRect))


if __name__ == "__main__":
    unittest.main()
