"""Small offscreen smoke tests. They do not touch the real desktop."""

from __future__ import annotations

import json
import os
import shutil
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QToolButton

from petapp.assets import CharacterAssets, CommonAssets
from petapp.config import Catalog, Settings, load_character, load_characters
from petapp.engine import WanderAction, WanderDecision
from petapp.manager import PetManager
from petapp.motion import MotionProfile
from petapp.paths import CHARACTERS_DIR, ICON_FILE, ITEMS_DIR
from petapp.theme import apply_app_style
from petapp.ui import (
    CharacterEditDialog,
    CharacterImportDialog,
    CharacterImportInfo,
    SettingsDialog,
)
from petapp.window import BUBBLE_FADE, BUBBLE_HOLD, PetWindow

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class MockManager:
    audio = None


def make_source_image(path: Path, *, striped: bool = False) -> None:
    """Paint a clearly organic placeholder "classmate" image."""

    image = QImage(480, 720, QImage.Format.Format_ARGB32)
    image.fill(QColor("#C9D8E8"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if striped:
        for i in range(20):
            painter.fillRect(0, i * 36, 480, 36, QColor(175 + i * 4, 120 + i * 5, 85 + i * 3))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#4A6FA5"))
    painter.drawRoundedRect(QRectF(120, 340, 240, 300), 30, 30)
    painter.setBrush(QColor("#F2C6A4"))
    painter.drawEllipse(QRectF(150, 120, 180, 210))
    painter.setBrush(QColor("#3E3457"))
    painter.drawEllipse(QRectF(135, 80, 210, 140))
    painter.drawEllipse(QRectF(185, 195, 24, 28))
    painter.drawEllipse(QRectF(270, 195, 24, 28))
    painter.setPen(QPen(QColor("#B34A4A"), 6))
    painter.drawArc(QRectF(210, 245, 60, 40), 200 * 16, 140 * 16)
    painter.setBrush(QColor("#F2C6A4"))
    painter.drawRoundedRect(QRectF(150, 500, 70, 150), 25, 25)
    painter.drawRoundedRect(QRectF(260, 500, 70, 150), 25, 25)
    painter.end()
    assert image.save(str(path), "PNG")


class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        DATA.mkdir(exist_ok=True)
        cls.app = QApplication.instance() or QApplication([])
        apply_app_style(cls.app)
        cls.catalog = Catalog.load(ITEMS_DIR)
        cls.characters = load_characters(CHARACTERS_DIR)
        cls.common = CommonAssets(cls.catalog, ICON_FILE)

    def make_window(self, index: int = 0, character=None) -> PetWindow:
        character = character or self.characters[index]
        assets = CharacterAssets(character, self.catalog, self.common)
        return PetWindow(
            MockManager(),
            character,
            self.catalog,
            assets,
            self.common,
            Settings(first_run=False, auto_watch=False),
            position=QPoint(40, 40),
            hint=False,
            drop_in=False,
        )

    def make_manager(self, name: str, *, characters_dir: Path | None = None) -> tuple[PetManager, Path]:
        tmp = DATA / name
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        manager = PetManager(
            self.app,
            self.characters,
            self.catalog,
            Settings(first_run=False, auto_watch=False, mischief_enabled=False),
            tmp / "settings.json",
            characters_dir=characters_dir or tmp / "characters",
        )
        return manager, tmp

    # ------------------------------------------------------------------
    # rendering / head regression
    # ------------------------------------------------------------------
    def test_godot_renderer_is_optional_and_degrades_cleanly(self) -> None:
        window = self.make_window(0)
        # Simulate a machine without Godot; the normal PyQt renderer remains.
        with mock.patch("petapp.godot_bridge.find_godot", return_value=None):
            self.assertFalse(window.enable_godot_renderer())
        self.assertIsNone(window._godot_bridge)
        window._sync_godot_renderer()  # no-op must not raise

    def test_window_can_render_and_default_head_is_visible(self) -> None:
        window = self.make_window()
        pixmap = QPixmap(window.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        window.render(pixmap)
        image = pixmap.toImage()
        self.assertGreater(image.width(), 100)
        self.assertGreater(image.height(), 200)
        opaque = 0
        for y in range(0, image.height(), 7):
            for x in range(0, image.width(), 7):
                if image.pixelColor(x, y).alpha() > 30:
                    opaque += 1
        self.assertGreater(opaque, 20)

        # Regression: the drawn head must be painted above the neck.  This
        # fails if the expression layer is blank / missing.
        hx, hy, hw, hh = window.config.head_rect
        left = int(window._side + hx * window._pet_w)
        top = int(window._top_space + hy * window._pet_h)
        right = int(window._side + (hx + hw) * window._pet_w)
        bottom = int(window._top_space + (hy + hh) * window._pet_h)
        head_pixels = 0
        for y in range(max(0, top), min(image.height(), bottom), 4):
            for x in range(max(0, left), min(image.width(), right), 4):
                if image.pixelColor(x, y).alpha() > 40:
                    head_pixels += 1
        self.assertGreater(head_pixels, 40, "默认头图必须在脖子以上正常渲染")

    def test_blank_expression_layer_falls_back_to_a_visible_head(self) -> None:
        tmp = DATA / "_blank_head_test"
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(CHARACTERS_DIR / "azhai", tmp / "azhai")
        blank = QImage(720, 1080, QImage.Format.Format_ARGB32)
        blank.fill(Qt.GlobalColor.transparent)
        self.assertTrue(blank.save(str(tmp / "azhai" / "heads" / "normal.png"), "PNG"))
        try:
            config = load_character(tmp / "azhai")
            assets = CharacterAssets(config, self.catalog, self.common)
            head = assets.compose_head("normal").toImage()
            opaque = sum(
                1
                for y in range(0, head.height(), 6)
                for x in range(0, head.width(), 6)
                if head.pixelColor(x, y).alpha() > 30
            )
            self.assertGreater(opaque, 20, "空白表情文件不能让默认头图消失")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_wardrobe_sprites_scale_to_each_character_socket(self) -> None:
        azhai = next(c for c in self.characters if c.slug == "azhai")
        elaina = next(c for c in self.characters if c.slug == "elaina")
        hat = self.catalog.item("witch_hat")
        self.assertIsNotNone(hat)
        source = self.common.pixmap(hat.file)
        azhai_assets = CharacterAssets(azhai, self.catalog, self.common)
        elaina_assets = CharacterAssets(elaina, self.catalog, self.common)
        azhai_rect = azhai_assets.mounted_rect(
            hat.mount, source, fit=hat.fit, offset=hat.offset
        )
        elaina_rect = elaina_assets.mounted_rect(
            hat.mount, source, fit=hat.fit, offset=hat.offset
        )
        self.assertGreater(azhai_rect.width(), 0.0)
        self.assertLess(azhai_rect.width(), azhai.canvas[0] * 0.9)
        self.assertNotAlmostEqual(
            azhai_rect.width(), elaina_rect.width(), places=2,
            msg="同一个道具必须按各角色 mount_points 自动缩放",
        )
        # It is centred on the named socket, never stretched to the full canvas.
        socket = elaina.mount_point("head_top")
        target = QPointF(
            socket.x * elaina.canvas[0] + hat.offset[0] * socket.width * elaina.canvas[0],
            socket.y * elaina.canvas[1] + hat.offset[1] * socket.width * elaina.canvas[0],
        )
        self.assertAlmostEqual(elaina_rect.center().x(), target.x(), places=3)
        self.assertAlmostEqual(elaina_rect.center().y(), target.y(), places=3)

    def test_hand_accessory_is_centred_on_the_hand_socket(self) -> None:
        elaina = next(c for c in self.characters if c.slug == "elaina")
        assets = CharacterAssets(elaina, self.catalog, self.common)
        item = self.catalog.item("milktea_hold")
        self.assertIsNotNone(item)
        source = self.common.pixmap(item.file)
        rect = assets.mounted_rect(item.mount, source, fit=item.fit, offset=item.offset)
        hand = elaina.mount_point("hand")
        target = QPointF(
            hand.x * elaina.canvas[0] + item.offset[0] * hand.width * elaina.canvas[0],
            hand.y * elaina.canvas[1] + item.offset[1] * hand.width * elaina.canvas[0],
        )
        self.assertAlmostEqual(rect.center().x(), target.x(), places=3)
        self.assertAlmostEqual(rect.center().y(), target.y(), places=3)
        self.assertLess(rect.width(), elaina.canvas[0] * 0.5)

    def test_food_and_book_are_mounted_at_sockets(self) -> None:
        window = self.make_window()
        config = window.config
        food = self.catalog.food("drumstick")
        self.assertIsNotNone(food)
        window.feed_item(food)
        self.assertIs(window._food_item, food)
        self.assertIsNotNone(window._food_pixmap)
        rect = window.assets.mounted_rect(
            food.mount,
            window._food_pixmap,
            fit=food.fit,
            offset=food.offset,
        )
        mouth = config.mount_point("mouth")
        self.assertTrue(
            rect.contains(QPointF(mouth.x * config.canvas[0], mouth.y * config.canvas[1])),
            msg="食物必须以 mouth 锚点为中心贴合",
        )
        window.study_now()
        book = self.catalog.prop("book")
        self.assertIsNotNone(book)
        rect = window.assets.mounted_rect(
            book.mount,
            window.assets.prop("book"),
            fit=book.fit,
            offset=book.offset,
        )
        hand = config.mount_point("hand")
        self.assertTrue(
            rect.contains(QPointF(hand.x * config.canvas[0], hand.y * config.canvas[1]))
        )

    def test_bust_mode_stays_put(self) -> None:
        config = replace(self.characters[0], bust_mode=True)
        window = self.make_window(character=config)
        window._start_walk()
        self.assertEqual(window.mode, "idle")
        window._start_climb(1)
        self.assertEqual(window.mode, "idle")
        window._next_decision = 0.0
        window._perform_idle_decision(time.monotonic())
        self.assertNotIn(window.mode, {"walk", "climb"})

    def test_autonomous_walk_sit_and_idle_doodles(self) -> None:
        elaina = next(c for c in self.characters if c.slug == "elaina")
        window = self.make_window(character=elaina)
        now = time.monotonic()

        window._start_walk(-1, duration=6.0)
        self.assertEqual(window.mode, "walk")
        self.assertEqual(window._current_pose(), "walk_left")
        self.assertAlmostEqual(window._walk_speed, 30.0)
        self.assertEqual(window._ticker.interval(), 16, "漫游应使用 60FPS")
        self.assertLess(window._facing, 0, "向左漫游应翻转朝向")
        window._direction = 1
        self.assertEqual(window._current_pose(), "walk_right")

        window._start_sit(duration=12.0)
        self.assertEqual(window.mode, "sit")
        self.assertEqual(window._current_pose(), "sit")
        self.assertGreaterEqual(window._sit_until, now + 10.5)
        self.assertLessEqual(window._sit_until, now + 13.0)

        window._interrupt_autonomy()
        self.assertEqual(window.mode, "idle", "交互必须打断坐下")
        self.assertGreaterEqual(window._next_decision, now + 7.0)

        decision = WanderDecision(
            action=WanderAction.IDLE,
            duration=9.0,
            doodle="tilt",
        )
        window._apply_idle_doodle(decision)
        self.assertIn(window._idle_tilt_angle, (-8.0, -6.0, 6.0, 8.0))
        self.assertGreater(window._idle_tilt_until, now)
        self.assertAlmostEqual(window._next_decision, now + 9.0, delta=0.2)

    def test_native_ratio_renders_and_head_inertia_is_bounded(self) -> None:
        elaina = next(c for c in self.characters if c.slug == "elaina")
        window = self.make_window(character=elaina)
        pixmap = QPixmap(window.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        window.render(pixmap)
        self.assertGreater(pixmap.toImage().width(), 100)
        for frame in range(60):
            window._pointer_vx = 1500 if frame % 2 else -1500
            window._set_mode("drag")
            window._update_head_inertia(1 / 60)
            self.assertLessEqual(abs(window._head_inertia), 6.0 + 1e-6)
        window._set_mode("idle")
        for _ in range(90):
            window._update_head_inertia(1 / 60)
        self.assertLess(abs(window._head_inertia), 0.2, "松手后头部应阻尼回正")

    def test_walk_uses_a_parabolic_hop_not_hard_translation(self) -> None:
        window = self.make_window(0)
        window._start_walk(1, duration=6.0)
        start_x = window._x
        self.assertGreater(window._hop_distance, 0)
        self.assertGreaterEqual(abs(window._hop_distance), 15.0)
        now = window._hop_cycle_started + window._hop.crouch_time + window._hop.air_time / 2
        window._hop_step(now, 1 / 60)
        self.assertGreater(window._x, start_x, "腾空时应向右前跃")
        self.assertLess(window._hop_y, 0, "腾空时应有抛物线高度")
        self.assertLess(window._hop_scale_y, 1.1)
        done_at = window._hop_cycle_started + window._hop.total_time + 0.01
        window._hop_step(done_at, 1 / 60)
        self.assertGreaterEqual(window._x, start_x + 15.0)
        window._interrupt_autonomy()
        self.assertEqual(window.mode, "idle")
        self.assertEqual(window._ticker.interval(), 33)
        self.assertEqual(window._hop_y, 0.0)

    def test_idle_engine_schedule_and_sit_expiry(self) -> None:
        elaina = next(c for c in self.characters if c.slug == "elaina")
        window = self.make_window(character=elaina)
        now = time.monotonic()
        window._interrupt_autonomy()
        self.assertGreaterEqual(window._next_decision - now, 7.5)
        self.assertLessEqual(window._next_decision - now, 15.5)

        decision = WanderDecision(
            action=WanderAction.SIT,
            duration=11.0,
        )
        with mock.patch.object(window._autonomy, "decide", return_value=decision):
            window._next_decision = 0.0
            window._perform_idle_decision(now)
        self.assertEqual(window.mode, "sit")
        self.assertEqual(window._current_expression(), "normal")
        window._sit_until = time.monotonic() - 1.0
        window._update_behavior(time.monotonic(), 1 / 60)
        self.assertEqual(window.mode, "idle")
        self.assertGreater(window._next_decision, time.monotonic())

    def test_idle_and_walk_have_a_low_frequency_anchor_bob(self) -> None:
        elaina = next(c for c in self.characters if c.slug == "elaina")
        window = self.make_window(character=elaina)
        window._set_mode("idle")
        samples = [window._anchor_bob(0.4 + i / 120.0) for i in range(360)]
        crossings = sum(
            1
            for a, b in zip(samples, samples[1:])
            if (a <= 0.0 < b) or (a >= 0.0 > b)
        )
        measured_hz = crossings / 2.0 / 3.0
        self.assertGreaterEqual(measured_hz, 1.1)
        self.assertLessEqual(measured_hz, 1.6)
        self.assertGreater(max(samples) - min(samples), 1.0, "应有轻微整体浮动")
        window._set_mode("drag")
        self.assertEqual(window._anchor_bob(1.0), 0.0, "悬空由拖拽倾角接管")

    def test_custom_multi_pose_idle_drag_and_sit_switch(self) -> None:
        tmp = DATA / "_multi_pose_switch_test"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        shutil.copytree(CHARACTERS_DIR / "azhai", tmp / "char")
        character_folder = tmp / "char"
        config_file = character_folder / "config.json"
        raw = json.loads(config_file.read_text(encoding="utf-8"))
        raw["layers"] = {"body": "body.png"}
        raw.pop("poses", None)
        config_file.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for legacy in ("body_walk.png", "body_dangle.png"):
            (character_folder / legacy).unlink(missing_ok=True)
        for name in ("idle.png", "sit.png", "drag.png"):
            shutil.copyfile(character_folder / "body.png", character_folder / name)
        character = load_character(character_folder)
        try:
            window = self.make_window(character=character)
            self.assertEqual(window._current_pose(), "idle")
            window._set_mode("drag")
            self.assertEqual(window._current_pose(), "drag")
            window._set_mode("idle")
            window._start_walk(1, duration=4.0)
            self.assertEqual(window._current_pose(), "idle", "小跳漫游使用 idle.png")
            now = time.monotonic()
            window._hop_step(now, 1 / 60)
            window._hop_cycle_started = now - (window._hop.crouch_time + window._hop.air_time + window._hop.land_time + 0.1)
            window._hop_step(now, 1 / 60)
            self.assertEqual(window._current_pose(), "sit", "漫游停顿切换 sit.png")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_pose_switch_for_drag_and_walk_textures(self) -> None:
        elaina = next(c for c in self.characters if c.slug == "elaina")
        window = self.make_window(character=elaina)
        self.assertEqual(window._current_pose(), "idle")
        window._set_mode("drag")
        self.assertEqual(window._current_pose(), "drag")
        window._set_mode("idle")
        window._direction = -1
        window._start_walk(-1, duration=4.0)
        self.assertEqual(window._current_pose(), "walk_left")
        window._interrupt_autonomy()
        self.assertEqual(window.mode, "idle")

    def test_new_pose_file_overrides_a_rigged_builtin_walk(self) -> None:
        tmp = DATA / "_rig_pose_override_test"
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(CHARACTERS_DIR / "xiaoman", tmp / "xiaoman")
        try:
            original = load_character(tmp / "xiaoman")
            original_window = self.make_window(character=original)
            self.assertTrue(original_window.assets.has_rig)
            self.assertFalse(
                original_window._uses_pose_texture("walk_left"),
                "内置 body_walk 层继续使用关节动画",
            )
            shutil.copyfile(tmp / "xiaoman" / "body.png", tmp / "xiaoman" / "walk_left.png")
            updated = load_character(tmp / "xiaoman")
            updated_window = self.make_window(character=updated)
            self.assertTrue(updated.has_dedicated_pose("walk_left"))
            self.assertTrue(
                updated_window._uses_pose_texture("walk_left"),
                "新增的 walk_left.png 应该覆盖关节走路姿态",
            )
            updated_window._start_walk(-1, duration=4.0)
            self.assertEqual(updated_window._current_pose(), "walk_left")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_hit_boxes_ignore_transparent_corners(self) -> None:
        window = self.make_window()
        w, h = window._pet_w, window._pet_h
        head = QPoint(
            round(window._side + (window.config.head_rect[0] + window.config.head_rect[2] / 2) * w),
            round(window._top_space + (window.config.head_rect[1] + window.config.head_rect[3] / 2) * h),
        )
        from PyQt6.QtCore import QPointF

        self.assertTrue(window._head_path_hit(QPointF(head)))
        self.assertFalse(window._valid_press_point(QPointF(0, 0)))
        self.assertFalse(window._valid_press_point(QPointF(window.width() - 1, 2)))

    def test_rig_layers_are_used_and_animate(self) -> None:
        window = self.make_window()
        self.assertTrue(window.assets.has_rig)
        self.assertIn("torso", window.config.parts)
        idle = QPixmap(window.size())
        idle.fill(Qt.GlobalColor.transparent)
        window.render(idle)
        bobs = []
        for frame in range(90):
            window._rig_pose = window._rig.update(1 / 60, mode="idle", now=frame / 60)
            bobs.append(window.rig_pose.bob)
        self.assertGreater(max(bobs) - min(bobs), 1.0, "待机应该有呼吸浮动")
        window._set_mode("drag")
        angles = []
        for frame in range(90):
            window._rig_pose = window._rig.update(
                1 / 60, vx=1500, mode="drag", now=frame / 60
            )
            angles.append(window.rig_pose.body_angle)
            self.assertLessEqual(abs(window.rig_pose.body_angle), 10.0)
            self.assertEqual(window.rig_pose.squash, 0.0)
            self.assertEqual(window.rig_pose.scale_y, 1.0)
        self.assertLess(min(angles), -3.0, "向右拖时身体应该平滑地向后倾")
        self.assertLessEqual(max(abs(a) for a in angles), 10.0 + 1e-6)
        self.assertGreater(window.rig_pose.drag, 0.9, "拖拽姿态应该完全混入")
        self.assertLess(abs(window.rig_pose.arm_left), 0.1)
        self.assertLess(abs(window.rig_pose.head_tilt), 0.1)
        self.assertEqual(
            window._current_expression(),
            "normal",
            "抓起时保持原始干净脸部，额外表现靠汗滴氛围图元",
        )
        dragged = QPixmap(window.size())
        dragged.fill(Qt.GlobalColor.transparent)
        window.render(dragged)
        self.assertNotEqual(idle.toImage(), dragged.toImage(), "拖拽姿势应该真的画出来")
        window._rig.land(620.0)
        window._rig_pose = window._rig.update(1 / 60, mode="idle", now=0.0)
        self.assertGreater(window.rig_pose.squash, 0.05, "落地应该蹲一下")
        self.assertLess(window.rig_pose.scale_y, 0.97)

    def test_drag_keeps_clean_face_and_uses_sweat_overlay(self) -> None:
        elaina = next(c for c in self.characters if c.slug == "elaina")
        window = self.make_window(character=elaina)
        self.assertIsNotNone(self.catalog.sweat_file)
        self.assertTrue(self.catalog.sweat_file.is_file())
        window._set_mode("drag")
        self.assertEqual(
            window._current_expression(),
            "normal",
            "抓起时不得切换到假表情或涂改 head.png",
        )
        self.assertTrue(elaina.face_static)
        self.assertNotIn("blink", elaina.expressions, "已删除自动派生表情")
        normal_face = window.assets.compose_head("normal").toImage()
        for expression in ("blink", "angry", "sleep", "happy", "hit"):
            self.assertEqual(
                window.assets.compose_head(expression).toImage(),
                normal_face,
                f"{expression} 也必须回退到原始 head.png",
            )
        window._start_sweat()
        window._update_sweat(time.monotonic(), 0.2)
        self.assertTrue(window._sweat_visible)
        self.assertGreater(window._sweat_alpha, 0.5)
        pm = QPixmap(window.size())
        pm.fill(Qt.GlobalColor.transparent)
        window.render(pm)
        self.assertGreater(pm.toImage().width(), 100)
        window._fade_sweat()
        window._update_sweat(time.monotonic(), 0.4)
        self.assertLess(window._sweat_alpha, 1.0, "落地后汗滴应淡出")
        self.assertEqual(window._ticker.interval(), 33, "低频悬空不再需要 60fps")
        window._set_mode("idle")
        self.assertEqual(window._ticker.interval(), 33)

    # ------------------------------------------------------------------
    # actions / bubbles
    # ------------------------------------------------------------------
    def test_actions_and_wardrobe(self) -> None:
        window = self.make_window(1)
        costumes = window.config.folder / "costumes"
        costumes.mkdir(exist_ok=True)
        self.addCleanup(lambda: costumes.rmdir() if costumes.is_dir() else None)
        window.pat(force=True)
        self.assertGreater(window.model.energy, 0)
        window.poke()
        self.assertGreater(window.model.anger, 0)
        window.toggle_wardrobe(self.catalog.items["cat_ears"])
        self.assertIn("cat_ears", window.accessories)
        window.toggle_wardrobe(self.catalog.items["sunglasses"])
        self.assertIn("sunglasses", window.accessories)
        window.toggle_wardrobe(self.catalog.items["milktea_hold"])
        self.assertIn("milktea_hold", window.accessories)
        self.assertFalse(hasattr(window, "outfit_id"), "服装逻辑已彻底移除")
        window.clear_wardrobe()
        self.assertEqual(window.accessories, ())

    def test_custom_character_without_costumes_cannot_wear_catalogue_items(self) -> None:
        custom = next(c for c in self.characters if c.slug == "azhai")
        window = self.make_window(character=custom)
        self.assertFalse(custom.has_costumes)
        self.assertEqual(window.accessories, (), "自定义立绘不得残留任何挂件")
        window.toggle_wardrobe(self.catalog.items["cat_ears"])
        self.assertEqual(window.accessories, ())
        window.clear_wardrobe()

    def test_eat_sleep_wake(self) -> None:
        window = self.make_window(2)
        window.model.hunger = 70
        window.feed_item(self.catalog.foods["milktea"])
        self.assertEqual(window.mode, "eat")
        self.assertLess(window.model.hunger, 70)
        window.sleep_now()
        self.assertTrue(window.sleeping)
        pixmap = QPixmap(window.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        window.render(pixmap)
        window.wake_up(by_user=True)
        self.assertFalse(window.sleeping)

    def test_sleep_has_no_bed_or_blanket_layer(self) -> None:
        elaina = next(c for c in self.characters if c.slug == "elaina")
        window = self.make_window(character=elaina)
        window.sleep_now()
        window._particles.clear()
        window._spawn_zzz(2)
        self.assertEqual(window._particles[-1].text, "💤")
        self.assertEqual(window._current_expression(), "normal")

        pixmap = QPixmap(window.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        with mock.patch.object(window.assets, "prop", wraps=window.assets.prop) as prop:
            window.render(pixmap)
        called = [call.args[0] for call in prop.call_args_list]
        self.assertNotIn("bed", called)
        self.assertNotIn("blanket", called)
        self.assertGreater(pixmap.toImage().width(), 100)

    def test_three_rapid_pokes_trigger_angry_combo(self) -> None:
        elaina = next(c for c in self.characters if c.slug == "elaina")
        window = self.make_window(character=elaina)
        window._bubble = None
        for _ in range(3):
            window.poke()
        self.assertGreater(window._combo_mark_until, 0.0)
        self.assertEqual(window._current_expression(), "normal")
        self.assertIsNotNone(window._bubble)
        self.assertIn(window._bubble.text, window.config.lines["rage"])
        pixmap = QPixmap(window.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        window.render(pixmap)
        self.assertGreater(pixmap.toImage().width(), 100)

    def test_default_click_uses_a_gentle_four_percent_jelly(self) -> None:
        window = self.make_window(0)
        now = time.monotonic()
        window._register_click(now)
        x, y = window._tap_bounce.scales(now)
        self.assertAlmostEqual(x, 1.04, places=5)
        self.assertAlmostEqual(y, 0.96, places=5)

    def test_click_squash_and_motion_profile_are_data_driven(self) -> None:
        profile = MotionProfile.from_mapping(
            {"tap": {"width": 0.08, "height": 0.03, "duration": 0.22}}
        )
        base = next(c for c in self.characters if c.slug == "elaina")
        window = self.make_window(character=replace(base, motion=profile))
        now = time.monotonic()
        window._register_click(now)
        x, y = window._tap_bounce.scales(now)
        self.assertAlmostEqual(x, 1.064, places=5)
        self.assertAlmostEqual(y, 0.976, places=5)
        self.assertAlmostEqual(window._tap_bounce._strength, 0.8, places=5)
        self.assertAlmostEqual(window._tap_bounce.duration, 0.22)
        self.assertIs(window._rig.profile, profile)

    def test_bubble_lasts_2_5_seconds_then_fades(self) -> None:
        window = self.make_window()
        window.say("测试气泡")
        bubble = window._bubble
        self.assertIsNotNone(bubble)
        self.assertAlmostEqual(bubble.hold_until - bubble.born, BUBBLE_HOLD, places=2)
        self.assertGreater(BUBBLE_FADE, 0.1)
        self.assertAlmostEqual(bubble.expires - bubble.hold_until, BUBBLE_FADE, places=2)
        self.assertGreater(bubble.alpha(bubble.hold_until - 0.05), 0.99)
        halfway = (bubble.hold_until + bubble.expires) / 2.0
        self.assertLess(bubble.alpha(halfway), 0.8)
        self.assertEqual(bubble.alpha(bubble.expires + 0.05), 0.0)

    def test_pat_feed_and_poke_pop_a_bubble(self) -> None:
        window = self.make_window()
        window._bubble = None
        window.pat(force=True)
        self.assertIsNotNone(window._bubble)
        self.assertIn(window._bubble.text, window.config.lines["pat"])
        window._bubble = None
        window.poke()
        self.assertIsNotNone(window._bubble)
        self.assertIn(window._bubble.text, window.config.lines["poke"] + window.config.lines["anger"])
        window._bubble = None
        window.feed_item(self.catalog.foods["milktea"])
        self.assertIsNotNone(window._bubble)
        self.assertIn(window._bubble.text, window.config.lines["feed"])

    def test_anger_rise_uses_anger_lines(self) -> None:
        window = self.make_window()
        window.model.anger = 26.0
        window._anger_band = 0
        line = window._note_anger_rise(24.0)
        self.assertIn(line, window.config.lines["anger"])
        self.assertEqual(window._note_anger_rise(window.model.anger), "")

    # ------------------------------------------------------------------
    # settings, scaling, import
    # ------------------------------------------------------------------
    def test_settings_panel_is_non_modal_and_not_globally_topmost(self) -> None:
        manager, tmp = self.make_manager("_nonmodal_settings_test")
        try:
            manager.spawn(self.characters[0], drop_in=False)
            manager.show_settings()
            QTest.qWait(80)
            dialog = manager._settings_dialog
            self.assertIsNotNone(dialog, "设置窗口应非阻塞地打开")
            assert dialog is not None
            self.assertTrue(dialog.isVisible())
            self.assertEqual(
                dialog.windowModality(),
                Qt.WindowModality.NonModal,
                "设置窗口不能阻塞宠物交互",
            )
            self.assertFalse(
                dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint,
                "设置窗口不应全局置顶，允许正常退到后台",
            )
            pet = manager.active_window
            self.assertIsNotNone(pet)
            assert pet is not None
            pet.poke()
            self.assertIsNotNone(pet._bubble, "设置窗口打开时桌宠仍应响应点击")
            dialog.close()
            QTest.qWait(40)
            self.assertIsNone(manager._settings_dialog)
            manager.shutdown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_settings_dialog_changes_model(self) -> None:
        manager, tmp = self.make_manager("_settings_gui_test")
        try:
            manager.spawn(self.characters[0], drop_in=False)
            dialog = SettingsDialog(manager)
            self.assertEqual(len(dialog._cards), len(self.characters))
            target_slug = self.characters[1].slug
            dialog._choose_character(target_slug)
            QTest.qWait(50)
            self.assertEqual(manager.active_window.config.slug, target_slug)
            dialog._max_spin.setValue(2)
            self.assertEqual(manager.settings.max_pets, 2)
            dialog.close()
            manager.shutdown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_display_size_defaults_to_40_and_has_new_range(self) -> None:
        manager, tmp = self.make_manager("_size_gui_test")
        try:
            window = manager.spawn(self.characters[0], drop_in=False)
            self.assertIsNotNone(window)
            self.assertAlmostEqual(window.scale, 0.4, places=2)
            self.assertAlmostEqual(manager.effective_scale(self.characters[0]), 0.4, places=2)
            self.assertEqual(int(100 * 0.2), 20)
            base_width = window.width()
            manager.set_character_scale(window.config.slug, 0.2)
            self.assertAlmostEqual(window.scale, 0.2, places=2)
            self.assertLess(window.width(), base_width)
            manager.set_character_scale(window.config.slug, 1.8)
            self.assertAlmostEqual(window.scale, 1.8, places=2)
            manager.set_character_scale(window.config.slug, 0.01)
            self.assertAlmostEqual(manager.settings.scales[window.config.slug], 0.2, places=2)
            restored = Settings.load(tmp / "settings.json")
            self.assertAlmostEqual(restored.scales[window.config.slug], 0.2, places=2)
            manager.shutdown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_settings_dialog_is_freely_resizable_and_cards_wrap(self) -> None:
        manager, tmp = self.make_manager("_resize_dialog_test")
        try:
            manager.spawn(self.characters[0], drop_in=False)
            dialog = SettingsDialog(manager)
            try:
                self.assertEqual(dialog.minimumWidth(), 760)
                self.assertLess(dialog.minimumWidth(), dialog.maximumWidth())
                dialog.show()
                QTest.qWait(80)
                dialog.resize(760, 720)
                QTest.qWait(80)
                narrow_columns = dialog._card_columns
                dialog.resize(1320, 780)
                QTest.qWait(80)
                self.assertGreater(dialog.width(), 1000, "设置窗口应该能横向拉宽")
                self.assertGreater(
                    dialog._card_columns,
                    narrow_columns,
                    "拉宽后每行应容纳更多角色卡片",
                )
                self.assertEqual(
                    dialog._cards_grid.count(),
                    len(dialog._card_widgets),
                    "所有角色卡片与导入按钮都应该在自适应网格里",
                )
                self.assertIs(
                    dialog._card_widgets[-1],
                    dialog._import_button,
                    "导入按钮必须固定排在卡片末尾",
                )
                index = dialog._cards_grid.indexOf(dialog._import_button)
                self.assertEqual(index, dialog._cards_grid.count() - 1)
                dialog.show()
                QTest.qWait(40)
                self.assertTrue(dialog._import_button.isVisible())
            finally:
                dialog.close()
                manager.shutdown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_repeated_imports_coexist_as_independent_cards(self) -> None:
        manager, tmp = self.make_manager("_multi_import_test")
        try:
            manager.spawn(self.characters[0], drop_in=False)
            source = tmp / "same_name.png"
            make_source_image(source)
            imported = []
            for _ in range(2):
                ok, _message, character = manager.import_character(
                    source,
                    name="同名同学",
                    subtitle="独立模型",
                    posture="stand",
                )
                self.assertTrue(ok)
                self.assertIsNotNone(character)
                imported.append(character)
            self.assertEqual(len(imported), 2)
            self.assertNotEqual(imported[0].slug, imported[1].slug)
            self.assertEqual(len({c.slug for c in imported}), 2)
            for character in imported:
                self.assertTrue(character.folder.is_dir())
                self.assertTrue((character.folder / "config.json").is_file())
                self.assertIn(character, manager.characters)
            self.assertGreaterEqual(len(manager.characters), len(self.characters) + 2)

            dialog = SettingsDialog(manager)
            try:
                self.assertEqual(len(dialog._cards), len(manager.characters))
                for character in imported:
                    self.assertIn(character.slug, dialog._cards)
            finally:
                dialog.close()
                manager.shutdown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_settings_dialog_exposes_import_and_size_controls(self) -> None:
        manager, tmp = self.make_manager("_dialog_gui_test")
        try:
            window = manager.spawn(self.characters[0], drop_in=False)
            dialog = SettingsDialog(manager)
            try:
                self.assertIn("导入新角色", dialog._import_button.text())
                self.assertEqual(len(dialog._cards), len(self.characters))
                self.assertEqual(dialog._nav.count(), 3)
                dialog._nav.setCurrentRow(1)
                self.assertEqual(dialog._pages.currentIndex(), 1)
                dialog._nav.setCurrentRow(2)
                self.assertEqual(dialog._pages.currentIndex(), 2)
                dialog._nav.setCurrentRow(0)
                self.assertTrue(dialog._size_slider.isEnabled())
                self.assertEqual(dialog._size_slider.minimum(), 20)
                self.assertEqual(dialog._size_slider.maximum(), 200)
                slug = window.config.slug
                dialog._size_slider.setValue(25)
                QTest.qWait(320)
                self.assertAlmostEqual(manager.settings.scales[slug], 0.25)
            finally:
                dialog.close()
                manager.shutdown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_import_character_from_dialog(self) -> None:
        manager, tmp = self.make_manager("_import_gui_test")
        try:
            window = manager.spawn(self.characters[0], drop_in=False)
            source = tmp / "my_anime_girl.png"
            make_source_image(source)
            dialog = SettingsDialog(manager)
            try:
                with mock.patch.object(
                    QFileDialog,
                    "getOpenFileName",
                    return_value=(str(source), "图片 (*.png)"),
                ), mock.patch.object(
                    dialog,
                    "_ask_character_info",
                    return_value=CharacterImportInfo(
                        name="小夏", subtitle="后排摸鱼冠军", posture="stand"
                    ),
                ):
                    dialog._on_import_character()
                QTest.qWait(80)
                self.assertEqual(len(manager.characters), len(self.characters) + 1)
                self.assertEqual(len(dialog._cards), len(manager.characters))
                new_character = manager.characters[-1]
                self.assertEqual(new_character.name, "小夏")
                self.assertEqual(new_character.subtitle, "后排摸鱼冠军")
                self.assertNotEqual(new_character.name, source.stem, "不能用文件名命名")
                self.assertIsNotNone(manager.active_window)
                self.assertEqual(manager.active_window.config.slug, new_character.slug)
                self.assertIn("导入", dialog._import_status.text())
                self.assertNotEqual(manager.active_window.config.slug, window.config.slug)
                pixmap = QPixmap(manager.active_window.size())
                pixmap.fill(Qt.GlobalColor.transparent)
                manager.active_window.render(pixmap)
                image = pixmap.toImage()
                opaque = sum(
                    1
                    for y in range(0, image.height(), 5)
                    for x in range(0, image.width(), 5)
                    if image.pixelColor(x, y).alpha() > 30
                )
                self.assertGreater(opaque, 10, "导入的角色必须能画出来")
            finally:
                dialog.close()
                manager.shutdown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_import_dialog_collects_name_subtitle_and_posture(self) -> None:
        dialog = CharacterImportDialog(None)
        try:
            self.assertFalse(dialog._accept_button.isEnabled(), "没填名字不能生成")
            dialog._name_edit.setText("小夏")
            dialog._subtitle_edit.setText("图书馆常驻NPC")
            dialog._posture_combo.setCurrentIndex(dialog._posture_combo.findData("sit"))
            self.assertTrue(dialog._accept_button.isEnabled())
            info = dialog.info()
            self.assertEqual(info.name, "小夏")
            self.assertEqual(info.subtitle, "图书馆常驻NPC")
            self.assertEqual(info.posture, "sit")
            self.assertTrue(dialog._name_edit.placeholderText(), "名称输入框应有引导而非文件名")
            self.assertEqual(dialog._name_edit.text(), "小夏")
        finally:
            dialog.close()

    def test_character_dialog_enter_saves_and_escape_cancels(self) -> None:
        dialog = CharacterImportDialog(None)
        try:
            dialog.show()
            QTest.qWait(40)
            self.assertFalse(
                dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint,
                "编辑/导入弹窗不应全局置顶",
            )
            self.assertTrue(dialog._accept_button.isDefault())
            self.assertTrue(dialog._accept_button.autoDefault())
            self.assertIs(dialog.save_btn, dialog._accept_button)
            dialog._name_edit.setText("回车同学")
            dialog._name_edit.returnPressed.emit()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        finally:
            dialog.close()

        edit = CharacterEditDialog(
            None,
            initial=CharacterImportInfo(
                name="回车同学", subtitle="已有头衔", posture="sit"
            ),
        )
        try:
            edit.show()
            QTest.qWait(40)
            self.assertEqual(edit._accept_button.text(), "保存修改")
            self.assertTrue(edit._accept_button.isDefault())
            edit._subtitle_edit.setText("新的头衔")
            edit._subtitle_edit.returnPressed.emit()
            self.assertEqual(edit.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(edit.info().subtitle, "新的头衔")
        finally:
            edit.close()

        cancelled = CharacterImportDialog(None)
        try:
            cancelled.show()
            cancelled._name_edit.setFocus()
            QTest.qWait(40)
            QTest.keyClick(cancelled._name_edit, Qt.Key.Key_Escape)
            self.assertEqual(cancelled.result(), QDialog.DialogCode.Rejected)
        finally:
            cancelled.close()

    def test_system_characters_are_locked_and_custom_can_be_deleted(self) -> None:
        manager, tmp = self.make_manager("_delete_gui_test")
        try:
            source = tmp / "temporary_classmate.png"
            make_source_image(source)
            ok, _message, custom = manager.import_character(
                source,
                name="临时同学",
                subtitle="待清理",
                posture="sit",
            )
            self.assertTrue(ok)
            self.assertIsNotNone(custom)
            assert custom is not None
            self.assertTrue(manager.can_delete_character(custom.slug))
            system = next(c for c in manager.characters if c.slug == "xiaoman")
            self.assertFalse(manager.can_delete_character(system.slug))
            ok, message = manager.delete_character(system.slug)
            self.assertFalse(ok)
            self.assertIn("系统初始角色", message)
            self.assertTrue(system.folder.is_dir())
            self.assertIn(system.slug, manager.by_slug)

            folder = custom.folder
            ok, message = manager.delete_character(custom.slug)
            self.assertTrue(ok)
            self.assertIn("已删除", message)
            self.assertFalse(folder.exists(), "角色目录必须被清理")
            self.assertNotIn(custom.slug, manager.by_slug)
            self.assertNotIn(custom.slug, manager.settings.scales)
            self.assertNotIn(custom.slug, [c.slug for c in manager.characters])
            manager.shutdown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_settings_card_delete_button_respects_lock(self) -> None:
        manager, tmp = self.make_manager("_delete_button_gui_test")
        try:
            source = tmp / "custom_card.png"
            make_source_image(source)
            ok, _message, custom = manager.import_character(
                source, name="可删同学", subtitle="自定义", posture="stand"
            )
            self.assertTrue(ok)
            assert custom is not None
            dialog = SettingsDialog(manager)
            try:
                system_card = dialog._cards["xiaoman"]
                system_buttons = system_card.findChildren(QToolButton)
                system_delete = next(
                    b for b in system_buttons if b.objectName() == "deleteCharacterCard"
                )
                self.assertFalse(system_delete.isEnabled())
                self.assertEqual(
                    system_delete.toolTip(),
                    "系统预置初始角色（不可删除）",
                )
                custom_card = dialog._cards[custom.slug]
                custom_delete = next(
                    b
                    for b in custom_card.findChildren(QToolButton)
                    if b.objectName() == "deleteCharacterCard"
                )
                self.assertTrue(custom_delete.isEnabled())
                with mock.patch.object(
                    QMessageBox,
                    "question",
                    return_value=QMessageBox.StandardButton.Yes,
                ):
                    dialog._confirm_delete_character(custom.slug)
                self.assertNotIn(custom.slug, dialog._cards)
                self.assertNotIn(custom.slug, manager.by_slug)
            finally:
                dialog.close()
                manager.shutdown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_import_is_cancelled_when_metadata_dialog_is_dismissed(self) -> None:
        manager, tmp = self.make_manager("_import_cancel_test")
        try:
            manager.spawn(self.characters[0], drop_in=False)
            source = tmp / "cancelled.png"
            make_source_image(source)
            dialog = SettingsDialog(manager)
            try:
                with mock.patch.object(
                    QFileDialog,
                    "getOpenFileName",
                    return_value=(str(source), "图片 (*.png)"),
                ), mock.patch.object(dialog, "_ask_character_info", return_value=None):
                    dialog._on_import_character()
                self.assertEqual(len(manager.characters), len(self.characters))
            finally:
                dialog.close()
                manager.shutdown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # context menu / tray behaviour
    # ------------------------------------------------------------------
    def test_context_menu_collapse_and_summon_another(self) -> None:
        manager, tmp = self.make_manager("_menu_gui_test")
        try:
            first = manager.spawn(self.characters[0], drop_in=False)
            self.assertIsNotNone(first)
            menu = manager.build_context_menu(first)
            try:
                labels = [action.text() for action in menu.actions()]
                self.assertIn("⚙️ 偏好设置…", labels)
                self.assertIn("收起至托盘", labels)
                self.assertIn("完全退出程序", labels)
                self.assertNotIn("送它回宿舍", labels)
                self.assertNotIn("退出桌角同学", labels)
                submenus = {action.text(): action.menu() for action in menu.actions() if action.menu()}
                self.assertIn("更换人物模型", submenus)
                self.assertIn("➕ 召唤同学到桌面", submenus)
                summon_menu = submenus["➕ 召唤同学到桌面"]
                summon_action = next(
                    action
                    for action in summon_menu.actions()
                    if action.isEnabled() and action.text().startswith("召唤")
                )
                summon_action.trigger()
                QTest.qWait(80)
                self.assertEqual(len(manager.windows), 2)
            finally:
                menu.deleteLater()

            # The same submenu toggles: visible -> collapse, hidden -> show.
            toggle_menu = manager.build_context_menu(first)
            try:
                toggle_submenu = next(
                    action.menu()
                    for action in toggle_menu.actions()
                    if action.text() == "➕ 召唤同学到桌面"
                )
                collapse_action = next(
                    action
                    for action in toggle_submenu.actions()
                    if action.text() == f"收起 {first.config.name}"
                )
                collapse_action.trigger()
                QTest.qWait(40)
            finally:
                toggle_menu.deleteLater()
            self.assertFalse(first.isVisible())
            self.assertIn(first, manager.windows)

            restore_menu = manager.build_context_menu(first)
            try:
                restore_submenu = next(
                    action.menu()
                    for action in restore_menu.actions()
                    if action.text() == "➕ 召唤同学到桌面"
                )
                show_action = next(
                    action
                    for action in restore_submenu.actions()
                    if action.text() == f"显示 {first.config.name}"
                )
                show_action.trigger()
                QTest.qWait(40)
            finally:
                restore_menu.deleteLater()
            self.assertTrue(first.isVisible())
            manager.shutdown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
