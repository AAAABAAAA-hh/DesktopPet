"""Render a polished README preview of Deskling without touching the desktop.

All states are staged in hidden widgets; the compositor uses the same paint
code as the real app, so the preview matches what the pets look like.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication

from petapp.assets import CharacterAssets, CommonAssets
from petapp.config import Catalog, Settings, load_characters
from petapp.paths import CHARACTERS_DIR, ICON_FILE, ITEMS_DIR, SCREENSHOTS_DIR
from petapp.theme import font
from petapp.window import PetWindow


class PreviewManager:
    audio = None


W, H = 1600, 1000
TASKBAR_TOP = 942


def rounded_fill(painter: QPainter, rect: QRectF, radius: float, colour) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.fillPath(path, colour)


def draw_background(painter: QPainter) -> None:
    base = QLinearGradient(0, 0, W, H)
    base.setColorAt(0.0, QColor("#F7EFE5"))
    base.setColorAt(0.52, QColor("#F2EDF8"))
    base.setColorAt(1.0, QColor("#E8F0F6"))
    painter.fillRect(QRectF(0, 0, W, H), base)

    blobs = [
        (-200, -210, 660, "#E6D8FA", 210),
        (1180, -180, 560, "#FFD9C6", 160),
        (480, 590, 760, "#DFF1E8", 150),
        (1020, 470, 460, "#DCE4FB", 100),
    ]
    painter.setPen(Qt.PenStyle.NoPen)
    for x, y, d, colour, alpha in blobs:
        grad = QRadialGradient(QPointF(x + d / 2, y + d / 2), d / 2)
        c = QColor(colour)
        c.setAlpha(alpha)
        grad.setColorAt(0.0, c)
        c2 = QColor(colour)
        c2.setAlpha(0)
        grad.setColorAt(1.0, c2)
        painter.setBrush(grad)
        painter.drawEllipse(QRectF(x, y, d, d))

    # tiny paper speckles
    painter.setBrush(QColor(90, 77, 65, 22))
    for i in range(90):
        x = (i * 151 + 73) % W
        y = (i * 83 + 31) % H
        r = 1.0 + (i % 3) * 0.7
        painter.drawEllipse(QPointF(x, y), r, r)

    # a pretend IDE window and a pretend video window behind the pets
    painter.setBrush(QColor(255, 253, 248, 154))
    painter.setPen(QPen(QColor(255, 255, 255, 200), 2))
    rounded_fill(painter, QRectF(62, 288, 610, 392), 22, QColor(255, 253, 248, 154))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#E1D4C2"))
    for i in range(3):
        painter.drawEllipse(QPointF(90 + i * 18, 316), 5, 5)
    painter.setPen(QColor(108, 94, 81, 160))
    painter.setFont(font(10))
    painter.drawText(QRectF(150, 304, 400, 22), Qt.AlignmentFlag.AlignLeft, "IDE — 你的论文终稿(真的).docx")
    code_colours = ["#A7B6D8", "#C6B7DA", "#A9C8BB", "#DFC1AB", "#B8C7D9"]
    widths = [270, 370, 220, 420, 300, 180, 350, 260]
    for i, width in enumerate(widths):
        y = 354 + i * 35
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(114, 100, 118, 26))
        painter.drawRoundedRect(QRectF(96, y, 26, 8), 4, 4)
        painter.setBrush(QColor(code_colours[i % len(code_colours)]))
        painter.drawRoundedRect(QRectF(132, y, width, 8), 4, 4)
    painter.setBrush(QColor(255, 255, 255, 78))
    painter.setPen(QPen(QColor(255, 255, 255, 150), 1.5))
    rounded_fill(painter, QRectF(1005, 272, 530, 404), 24, QColor(49, 49, 67, 62))
    painter.setPen(QColor(255, 255, 255, 175))
    painter.setFont(font(10))
    painter.drawText(QRectF(1032, 290, 300, 24), Qt.AlignmentFlag.AlignLeft, "摸鱼视频 · 4K 超清")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 38))
    painter.drawRoundedRect(QRectF(1030, 326, 480, 310), 16, 16)
    # play triangle
    tri = QPainterPath()
    tri.moveTo(1245, 428)
    tri.lineTo(1245, 536)
    tri.lineTo(1325, 482)
    tri.closeSubpath()
    painter.setBrush(QColor(255, 255, 255, 118))
    painter.drawPath(tri)
    painter.setPen(QColor(255, 255, 255, 95))
    painter.setFont(font(8))
    painter.drawText(QRectF(1032, 646, 450, 20), Qt.AlignmentFlag.AlignRight, "已看 3 小时 · 进度 99%")

    # title block
    painter.setPen(QColor("#3B3340"))
    painter.setFont(font(52, QFont.Weight.Black))
    painter.drawText(QPointF(74, 140), "桌角同学")
    painter.setPen(QColor("#8A7562"))
    painter.setFont(font(19, QFont.Weight.Medium))
    painter.drawText(QPointF(76, 181), "Deskling · 把宿舍同学养成桌面纸片人")
    painter.setFont(font(14))
    painter.setPen(QColor(112, 98, 87, 210))
    painter.drawText(QPointF(78, 219), "透明置顶 · 拎起来会自由落体 · 摸头会消气 · 饿了会骂人")

    chips = [("透明置顶", "#7B68EE"), ("可拎可摔", "#E57862"), ("会记仇", "#58A78B")]
    x = 1120
    painter.setFont(font(10, QFont.Weight.DemiBold))
    for text, accent in chips:
        metrics = painter.fontMetrics()
        w = metrics.horizontalAdvance(text) + 28
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 253, 248, 170))
        painter.drawRoundedRect(QRectF(x, 82, w, 31), 15, 15)
        painter.setBrush(QColor(accent))
        painter.drawEllipse(QPointF(x + 14, 97.5), 3.5, 3.5)
        painter.setPen(QColor(80, 69, 62))
        painter.drawText(QRectF(x + 24, 82, w - 30, 31), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        x += w + 9

    # app sticker top-right
    icon = QPixmap(str(ICON_FILE))
    if not icon.isNull():
        painter.drawPixmap(QRectF(1414, 127, 112, 112), icon, QRectF(icon.rect()))

    # taskbar
    painter.setPen(QPen(QColor(255, 255, 255, 170), 1.2))
    rounded_fill(painter, QRectF(0, TASKBAR_TOP, W, H - TASKBAR_TOP + 8), 0, QColor(250, 247, 242, 235))
    painter.setPen(QPen(QColor(216, 203, 188, 120), 1))
    painter.drawLine(0, TASKBAR_TOP, W, TASKBAR_TOP)
    # launcher icons / pseudo app icons
    painter.setPen(Qt.PenStyle.NoPen)
    for i, colour in enumerate(("#8B79F2", "#F5B26B", "#75B6A5", "#E48080")):
        painter.setBrush(QColor(colour))
        painter.drawRoundedRect(QRectF(34 + i * 44, TASKBAR_TOP + 14, 29, 29), 8, 8)
    painter.setBrush(QColor(70, 62, 58, 180))
    painter.drawEllipse(QPointF(240, TASKBAR_TOP + 28), 3, 3)
    painter.setFont(font(9))
    painter.setPen(QColor(95, 82, 73, 210))
    painter.drawText(
        QRectF(254, TASKBAR_TOP + 14, 300, 30),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        "桌角同学已上线",
    )
    painter.setFont(font(10))
    painter.drawText(
        QRectF(636, TASKBAR_TOP + 12, 430, 36),
        Qt.AlignmentFlag.AlignCenter,
        "右键桌宠可以投喂 / 换装 / 惹它生气",
    )
    painter.setFont(font(9))
    painter.setPen(QColor(100, 87, 77, 190))
    painter.drawText(
        QRectF(1170, TASKBAR_TOP + 15, 286, 30),
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        "23:59  ·  周五",
    )
    # app icon in taskbar
    if not icon.isNull():
        painter.drawPixmap(QRectF(1480, TASKBAR_TOP + 8, 38, 38), icon, QRectF(icon.rect()))


def prepare_window(
    window: PetWindow,
    *,
    accessories: tuple[str, ...] = (),
    bubble: str = "",
    expression: str = "",
    hearts: int = 0,
    sparkles: int = 0,
    sleeping: bool = False,
    studying: bool = False,
) -> None:
    window._greet_due = None
    window._hint_due = None
    window._next_decision = 1e20
    window._next_chatter = 1e20
    window._next_climb_allowed = 1e20
    window._greeted = True
    window._accessories = accessories
    window.tidy_for_capture()
    window._y = window._ground_window_y()
    window.move(round(window._x), round(window._y))
    window._vx = 0
    window._vy = 0
    if sleeping:
        window.sleep_now(auto=True)
        window._bubble = None
        window._spawn_zzz(2)
    elif studying:
        window.study_now()
        window._bubble = None
    else:
        window._set_mode("idle")
        if expression:
            window.model.pulse(expression, 30)
    if bubble:
        window._bubble = None
        window.say(bubble, priority=1)
        if window._bubble is not None:
            now = time.monotonic()
            window._bubble.born = now - 1.0
            window._bubble.hold_until = now + 400.0
            window._bubble.expires = now + 400.0 + 0.4
    if hearts:
        window._spawn_hearts(hearts)
    if sparkles:
        window._spawn_sparkles(sparkles)


def render_window(window: PetWindow) -> QPixmap:
    pm = QPixmap(window.width() * 2, window.height() * 2)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.scale(2.0, 2.0)
    window.render(painter)
    painter.end()
    return pm


def build_preview() -> Path:
    app = QApplication.instance() or QApplication([])
    catalog = Catalog.load(ITEMS_DIR)
    characters = {c.slug: c for c in load_characters(CHARACTERS_DIR)}
    if not characters:
        raise SystemExit("no characters found")
    common = CommonAssets(catalog, ICON_FILE)
    manager = PreviewManager()
    settings = Settings(first_run=False, auto_watch=False, mischief_enabled=False)

    specs = [
        ("azhai", dict(accessories=("sunglasses",), sparkles=3)),
        (
            "xiaoman",
            dict(
                accessories=("cat_ears",),
                bubble="摸鱼吗？带我一个！",
                expression="happy",
                hearts=5,
            ),
        ),
        ("laowang", dict(sleeping=True)),
        (
            "linlin",
            dict(
                bubble="图书馆的座位我帮你占了。",
                expression="smug",
                studying=True,
            ),
        ),
    ]
    windows: list[PetWindow] = []
    for slug, kwargs in specs:
        config = characters.get(slug) or list(characters.values())[len(windows)]
        assets = CharacterAssets(config, catalog, common)
        window = PetWindow(
            manager,
            config,
            catalog,
            assets,
            common,
            settings,
            position=QPoint(80, 100),
            hint=False,
            drop_in=False,
        )
        prepare_window(window, **kwargs)
        windows.append(window)

    rendered = [render_window(w) for w in windows]
    gaps = 12
    total = sum(w.width() for w in windows) + gaps * (len(windows) - 1)
    start_x = (W - total) / 2
    x = start_x
    positions: list[float] = []
    for window in windows:
        positions.append(x)
        x += window.width() + gaps

    image = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#F6EFE6"))
    painter = QPainter(image)
    painter.setRenderHints(
        QPainter.RenderHint.Antialiasing
        | QPainter.RenderHint.TextAntialiasing
        | QPainter.RenderHint.SmoothPixmapTransform
    )
    draw_background(painter)

    # draw pets above the desktop, in left-to-right order
    for window, pm, px in zip(windows, rendered, positions):
        logical_w = window.width()
        logical_h = window.height()
        bottom = TASKBAR_TOP + 2
        target = QRectF(px, bottom - logical_h, logical_w, logical_h)
        source = QRectF(0, 0, pm.width(), pm.height())
        painter.drawPixmap(target, pm, source)

    # a few decorative hearts / sparkles in the free space
    painter.setPen(Qt.PenStyle.NoPen)
    for i, (x0, y0, s, colour) in enumerate(
        ((1190, 256, 9, "#F39AAD"), (1210, 274, 5, "#FFD0D8"), (790, 242, 6, "#FFD166"))
    ):
        petal = QPainterPath()
        petal.moveTo(x0, y0 + s)
        petal.cubicTo(x0 - s * 1.8, y0 - s * 0.1, x0 - s * 0.6, y0 - s * 1.1, x0, y0 - s * 0.3)
        petal.cubicTo(x0 + s * 0.6, y0 - s * 1.1, x0 + s * 1.8, y0 - s * 0.1, x0, y0 + s)
        painter.fillPath(petal, QColor(colour))

    painter.end()

    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    output = SCREENSHOTS_DIR / "preview.png"
    image.save(str(output), "PNG")
    for window in windows:
        window.dispose()
    app.processEvents()
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="render a Deskling preview image")
    parser.add_argument("--out", type=Path, default=None, help="override output path")
    args = parser.parse_args()
    try:
        out = build_preview()
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            out.replace(args.out)
            out = args.out
        print(f"preview written: {out}")
        return 0
    except Exception:
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
