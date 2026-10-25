"""Render the README screenshots for the animation and custom-import upgrade.

Usage:
    python tools/capture_upgrade.py

Everything is staged offscreen; no window is shown on the desktop.  The demo
"classmate images" are paint-program placeholders, never real people.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from PyQt6.QtCore import QPoint, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from petapp import importer  # noqa: E402
from petapp.assets import CharacterAssets, CommonAssets  # noqa: E402
from petapp.config import Catalog, Settings, load_characters  # noqa: E402
from petapp.manager import PetManager  # noqa: E402
from petapp.paths import CHARACTERS_DIR, ICON_FILE, ITEMS_DIR, SCREENSHOTS_DIR  # noqa: E402
from petapp.theme import apply_app_style  # noqa: E402
from petapp.ui import SettingsDialog  # noqa: E402
from petapp.window import PetWindow  # noqa: E402

TMP = ROOT / "data" / "_capture_upgrade"


class PreviewManager:
    audio = None


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    ):
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                pass
    return ImageFont.load_default()


def _render_window(window: PetWindow, scale: float = 2.0) -> QPixmap:
    pixmap = QPixmap(round(window.width() * scale), round(window.height() * scale))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHints(
        QPainter.RenderHint.Antialiasing
        | QPainter.RenderHint.SmoothPixmapTransform
        | QPainter.RenderHint.TextAntialiasing
    )
    painter.scale(scale, scale)
    window.render(painter)
    painter.end()
    return pixmap


def _new_window(config, catalog, common, settings, *, scale: float = 0.92) -> PetWindow:
    window = PetWindow(
        PreviewManager(),
        config,
        catalog,
        CharacterAssets(config, catalog, common),
        common,
        settings,
        position=QPoint(60, 80),
        hint=False,
        drop_in=False,
        scale=scale,
    )
    window._greet_due = None
    window._hint_due = None
    window._next_decision = 1e20
    window._next_chatter = 1e20
    window._next_hunger = 1e20
    return window


def _pose(window: PetWindow, *, seconds: float, mode: str = "idle", vx: float = 0.0,
          vy: float = 0.0) -> None:
    if window.mode != mode:
        window._set_mode(mode)
    frames = max(1, int(seconds * 60))
    for frame in range(frames):
        window._rig_pose = window._rig.update(
            1 / 60,
            vx=vx,
            vy=vy,
            mode=mode,
            now=frame / 60,
            direction=1 if vx >= 0 else -1,
        )


def _trim(image: Image.Image, pad: int = 8) -> Image.Image:
    bbox = image.getbbox()
    if not bbox:
        return image
    left, top, right, bottom = bbox
    return image.crop(
        (
            max(0, left - pad),
            max(0, top - pad),
            min(image.width, right + pad),
            min(image.height, bottom + pad),
        )
    )


def _fixed_crop(pixmap: QPixmap) -> Image.Image:
    """Crop the pet area without per-pose re-centering (keeps squash visible)."""

    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    image = image.copy(0, round(image.height() * 0.16), image.width(), round(image.height() * 0.84))
    data = bytes(image.constBits().asstring(image.sizeInBytes()))
    return Image.frombytes("RGBA", (image.width(), image.height()), data)


def _compose_sheet(entries: list[tuple[Image.Image, str, str]], columns: int,
                   cell: tuple[int, int], path: Path) -> None:
    cell_w, cell_h = cell
    rows = math.ceil(len(entries) / columns)
    sheet = Image.new("RGBA", (columns * cell_w, rows * cell_h), "#F7F0E5")
    draw = ImageDraw.Draw(sheet)
    title_font = _font(24)
    hint_font = _font(17)
    for index, (image, title, hint) in enumerate(entries):
        col, row = index % columns, index // columns
        x0 = col * cell_w
        y0 = row * cell_h
        draw.rectangle((x0, y0, x0 + cell_w - 1, y0 + cell_h - 1), outline="#E4D7C7", width=2)
        draw.text((x0 + 20, y0 + 15), title, font=title_font, fill="#3B3340")
        draw.text((x0 + 20, y0 + 47), hint, font=hint_font, fill="#8A7562")
        thumb = image.copy()
        thumb.thumbnail((cell_w - 34, cell_h - 86), Image.Resampling.LANCZOS)
        sheet.alpha_composite(
            thumb,
            (x0 + (cell_w - thumb.width) // 2, y0 + 80 + (cell_h - 88 - thumb.height) // 2),
        )
    sheet.convert("RGB").save(path, optimize=True)


def build_motion(catalog, config, common, settings) -> Path:
    entries: list[tuple[Image.Image, str, str]] = []
    for index, time_s in enumerate((0.0, 0.9, 1.8, 2.7)):
        window = _new_window(config, catalog, common, settings)
        _pose(window, seconds=time_s)
        entries.append((_fixed_crop(_render_window(window)), f"待机呼吸 {chr(65 + index)}",
                        "胸腹起伏 · 脑袋慢半拍"))
        window.dispose()
    # Let the damped tilt settle in both directions so the sheet shows the
    # inertial lean rather than two near-upright frames.
    for label, vx in (("向右拖", 1500.0), ("向左拖", -1500.0)):
        window = _new_window(config, catalog, common, settings)
        _pose(window, seconds=1.0, mode="drag", vx=vx)
        entries.append((_fixed_crop(_render_window(window)), f"悬空 · {label}",
                        "干净原脸 · ±10° 阻尼惯性倾角 · 汗滴 · 低频浮动"))
        window.dispose()
    window = _new_window(config, catalog, common, settings)
    _pose(window, seconds=0.45, mode="fall", vx=350.0, vy=850.0)
    entries.append((_fixed_crop(_render_window(window)), "自由落体", "轻微拉伸 · 手脚乱晃"))
    window.dispose()
    window = _new_window(config, catalog, common, settings)
    window._rig.land(620.0)
    window._rig_pose = window._rig.update(1 / 60, mode="idle", now=0.0)
    entries.append((_fixed_crop(_render_window(window)), "落地回弹", "下蹲压缩 · 弹簧回正"))
    window.dispose()
    output = SCREENSHOTS_DIR / "motion.png"
    _compose_sheet(entries, 4, (360, 560), output)
    return output


def _paint_anime(path: Path) -> None:
    image = QImage(520, 760, QImage.Format.Format_ARGB32)
    image.fill(QColor("#FFFFFF"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    # hair, face, hoodie, skirt, legs, shoes — a deliberately generic anime doll
    painter.setBrush(QColor("#3E3457"))
    painter.drawEllipse(QRectF(145, 70, 230, 260))
    painter.setBrush(QColor("#FFD9C2"))
    painter.drawEllipse(QRectF(165, 120, 190, 220))
    painter.setBrush(QColor("#6B5585"))
    painter.drawEllipse(QRectF(200, 205, 34, 42))
    painter.drawEllipse(QRectF(286, 205, 34, 42))
    painter.setPen(QPen(QColor("#B34A4A"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawArc(QRectF(232, 262, 58, 38), 200 * 16, 140 * 16)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#8B79F2"))
    painter.drawRoundedRect(QRectF(150, 350, 220, 260), 32, 32)
    painter.setBrush(QColor("#44405E"))
    painter.drawRoundedRect(QRectF(165, 575, 190, 95), 22, 22)
    painter.setBrush(QColor("#FFD9C2"))
    painter.drawRoundedRect(QRectF(190, 650, 55, 105), 20, 20)
    painter.drawRoundedRect(QRectF(275, 650, 55, 105), 20, 20)
    painter.setPen(QPen(QColor("#3B3340"), 4))
    painter.setBrush(QColor("#F3B7AD"))
    painter.drawEllipse(QRectF(170, 735, 95, 30))
    painter.drawEllipse(QRectF(255, 735, 95, 30))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#FFD166"))
    painter.drawEllipse(QRectF(247, 420, 26, 26))
    painter.end()
    image.save(str(path), "PNG")


def _paint_photo(path: Path) -> None:
    image = QImage(520, 700, QImage.Format.Format_RGB32)
    image.fill(QColor("#C9D8E8"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # busy striped background -> exercises the paper-sticker fallback
    for i in range(22):
        painter.fillRect(0, i * 32, 520, 32, QColor(178 + i * 3, 122 + i * 4, 88 + i * 2))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#5D6C8B"))
    painter.drawEllipse(QRectF(90, 380, 340, 280))
    painter.setBrush(QColor("#F2C6A4"))
    painter.drawEllipse(QRectF(155, 120, 210, 250))
    painter.setBrush(QColor("#3E3457"))
    painter.drawEllipse(QRectF(140, 80, 240, 150))
    painter.setBrush(QColor("#3B3340"))
    painter.drawEllipse(QRectF(195, 205, 26, 30))
    painter.drawEllipse(QRectF(300, 205, 26, 30))
    painter.setPen(QPen(QColor("#B34A4A"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawArc(QRectF(230, 265, 60, 42), 200 * 16, 140 * 16)
    painter.end()
    image.save(str(path), "PNG")


def build_import_demo(catalog, common, settings) -> Path:
    TMP.mkdir(parents=True, exist_ok=True)
    chars_dir = TMP / "demo_characters"
    shutil.rmtree(chars_dir, ignore_errors=True)
    chars_dir.mkdir(parents=True)
    anime_source = TMP / "anime_stand.png"
    photo_source = TMP / "classmate_photo.png"
    _paint_anime(anime_source)
    _paint_photo(photo_source)
    anime = importer.create_character(anime_source, chars_dir)
    photo = importer.create_character(photo_source, chars_dir)
    entries: list[tuple[Image.Image, str, str]] = []
    for character, title, hint in (
        (anime, "导入二次元立绘", "自动去背景 · 可呼吸 / 拖拽 / 溜达"),
        (photo, "导入真人照片", "复杂背景自动变照片贴纸 · 固定站立"),
    ):
        window = _new_window(character, catalog, common, settings, scale=1.15)
        _pose(window, seconds=1.1)
        entries.append((_trim(_fixed_crop(_render_window(window))), title, hint))
        window.dispose()
    output = SCREENSHOTS_DIR / "custom_character.png"
    _compose_sheet(entries, 2, (430, 620), output)
    return output


def build_elaina(catalog, characters, common, settings) -> Path:
    elaina = next((c for c in characters if c.slug == "elaina"), None)
    if elaina is None:
        raise SystemExit("elaina character is missing")
    window = _new_window(elaina, catalog, common, settings, scale=1.15)
    _pose(window, seconds=1.1)
    image = _trim(_fixed_crop(_render_window(window)), pad=10)
    output = SCREENSHOTS_DIR / "elaina.png"
    image.save(output, optimize=True)
    window.dispose()
    return output


def build_elaina_actions(catalog, characters, common, settings) -> Path:
    """Action sheet for Elaina, including the calm damped suspended pose."""

    elaina = next((c for c in characters if c.slug == "elaina"), None)
    if elaina is None:
        raise SystemExit("elaina character is missing")
    entries: list[tuple[Image.Image, str, str]] = []

    window = _new_window(elaina, catalog, common, settings, scale=1.15)
    _pose(window, seconds=1.1)
    entries.append((_fixed_crop(_render_window(window)), "待机呼吸", "轻微起伏 + 眨眼"))
    window.dispose()

    window = _new_window(elaina, catalog, common, settings, scale=1.15)
    window._tap_bounce.trigger(time.monotonic(), strength=1.0)
    entries.append((_fixed_crop(_render_window(window)), "点击 Q 弹", "宽度 +5% / 高度 -5%"))
    window.dispose()

    window = _new_window(elaina, catalog, common, settings, scale=1.15)
    window._trigger_combo(time.monotonic())
    entries.append((_fixed_crop(_render_window(window)), "连击 3 次", "跳动怒火 + 红温 + 台词"))
    window.dispose()

    for index in range(2):
        window = _new_window(elaina, catalog, common, settings, scale=1.15)
        _pose(window, seconds=1.0, mode="drag", vx=1200.0 if index == 0 else -1200.0)
        entries.append(
            (
                _fixed_crop(_render_window(window)),
                "悬空 · 向右拖" if index == 0 else "悬空 · 向左拖",
                "干净原脸 · 阻尼惯性倾角 · 汗滴 · 低频浮动",
            )
        )
        window.dispose()

    window = _new_window(elaina, catalog, common, settings, scale=1.15)
    window.sleep_now(auto=True)
    window._bubble = None
    window._spawn_zzz(2)
    window._rig_pose = window._rig.update(
        1 / 60, mode="sleep", sleeping=True, now=1.0
    )
    entries.append((_fixed_crop(_render_window(window)), "睡觉", "呼吸 + Zzz"))
    window.dispose()

    window = _new_window(elaina, catalog, common, settings, scale=1.15)
    window.study_now()
    window._bubble = None
    entries.append((_fixed_crop(_render_window(window)), "学习", "课本 hand 锚点"))
    window.dispose()

    window = _new_window(elaina, catalog, common, settings, scale=1.15)
    food = catalog.food("drumstick")
    if food is not None:
        window.feed_item(food)
        window._bubble = None
    entries.append((_fixed_crop(_render_window(window)), "投喂", "食物 mouth 锚点"))
    window.dispose()

    output = SCREENSHOTS_DIR / "elaina_actions.png"
    _compose_sheet(entries, 4, (300, 560), output)
    return output


def build_settings(app, catalog, characters) -> Path:
    settings_root = TMP / "settings"
    shutil.rmtree(settings_root, ignore_errors=True)
    settings_root.mkdir(parents=True)
    settings = Settings(
        first_run=False,
        auto_watch=False,
        mischief_enabled=False,
        max_pets=4,
        last_character=characters[0].slug,
    )
    manager = PetManager(
        app,
        characters,
        catalog,
        settings,
        settings_root / "settings.json",
        characters_dir=CHARACTERS_DIR,
        items_dir=ITEMS_DIR,
    )
    window = manager.spawn(characters[0], drop_in=False)
    if window is not None:
        window._bubble = None
    dialog = SettingsDialog(manager)
    try:
        dialog.show()
        app.processEvents()
        dialog.resize(1100, 760)
        app.processEvents()
        scale = 2.0
        pixmap = QPixmap(round(dialog.width() * scale), round(dialog.height() * scale))
        pixmap.fill(QColor("#F7F0E5"))
        painter = QPainter(pixmap)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.scale(scale, scale)
        dialog.render(painter)
        painter.end()
        output = SCREENSHOTS_DIR / "settings.png"
        pixmap.save(str(output), "PNG")
    finally:
        dialog.close()
        manager.shutdown()
    return output


def main() -> int:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    apply_app_style(app)
    catalog = Catalog.load(ITEMS_DIR)
    characters = load_characters(CHARACTERS_DIR)
    if not characters:
        raise SystemExit("no characters found")
    common = CommonAssets(catalog, ICON_FILE)
    settings = Settings(first_run=False, auto_watch=False, mischief_enabled=False)
    motion = build_motion(catalog, characters[0], common, settings)
    custom = build_import_demo(catalog, common, settings)
    elaina = build_elaina(catalog, characters, common, settings)
    elaina_actions = build_elaina_actions(catalog, characters, common, settings)
    settings_shot = build_settings(app, catalog, characters)
    print(f"motion:   {motion}")
    print(f"custom:   {custom}")
    print(f"elaina:   {elaina}")
    print(f"actions:  {elaina_actions}")
    print(f"settings: {settings_shot}")
    shutil.rmtree(TMP, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
