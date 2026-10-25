"""Desktop-wide mischief: the rage overlay, sticky notes and mouse thief."""

from __future__ import annotations

import math
import random
from typing import Callable

from PyQt6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QWidget

from . import win32
from .config import CharacterConfig
from .theme import font


class RageOverlay(QWidget):
    """A short-lived giant angry face in the middle of the screen."""

    finished = pyqtSignal()

    def __init__(
        self,
        screen_rect: QRect,
        head_pixmap: QPixmap,
        config: CharacterConfig,
        rage_line: str,
        duration: float = 3.1,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setGeometry(screen_rect)
        self._head = head_pixmap
        self._config = config
        self._line = rage_line
        self._duration = max(1.2, duration)
        self._clock = QElapsedTimer()
        self._rng = random.Random(config.order * 97 + 13)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._update_animation)
        self._closed = False

    def start(self) -> None:
        self._clock.start()
        self._timer.start()
        self.show()
        self.raise_()

    def _check_end(self) -> None:
        if self._clock.elapsed() / 1000.0 >= self._duration and not self._closed:
            self._closed = True
            self._timer.stop()
            self.close()
            self.finished.emit()

    def _update_animation(self) -> None:
        # keep the animation active even if the first call is concurrent
        self.update()
        self._check_end()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        if not self._closed:
            self._closed = True
            self.finished.emit()
        super().closeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        elapsed = max(0.0, self._clock.elapsed() / 1000.0)
        intro = min(1.0, elapsed / 0.28)
        # ease-out with a little overshoot
        eased = 1 - (1 - intro) ** 3
        outro = 1.0
        if elapsed > self._duration - 0.35:
            outro = max(0.0, (self._duration - elapsed) / 0.35)
        pulse = 1.0 + math.sin(elapsed * 17.0) * 0.018
        shake_x = math.sin(elapsed * 55) * 8 * intro
        shake_y = math.cos(elapsed * 47) * 5 * intro

        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(max(0.0, min(1.0, outro * eased)))

        rect = self.rect()
        cx = rect.center().x()
        cy = rect.height() * 0.36

        # dark red vignette
        vignette = QRadialGradient(QPointF(cx, cy), max(rect.width(), rect.height()) * 0.7)
        vignette.setColorAt(0.0, QColor(74, 18, 28, 205))
        vignette.setColorAt(0.55, QColor(57, 14, 23, 145))
        vignette.setColorAt(1.0, QColor(20, 8, 14, 70))
        painter.fillRect(rect, vignette)

        # action lines radiating outwards
        painter.save()
        painter.translate(cx, cy)
        line_color = QColor(255, 208, 112, 160)
        for i in range(22):
            angle = (i / 22) * math.tau + elapsed * 0.12
            radius = min(rect.width(), rect.height()) * (0.31 + 0.04 * ((i * 7) % 5) / 4)
            inner = radius * 0.78
            painter.setPen(QPen(line_color, 3.0 + (i % 3) * 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(
                QPointF(math.cos(angle) * inner, math.sin(angle) * inner * 0.55),
                QPointF(math.cos(angle) * radius, math.sin(angle) * radius * 0.55),
            )
        painter.restore()

        # the giant head, carefully mapped out of the full-canvas sprite
        if not self._head.isNull():
            cw, ch = self._config.canvas
            hx, hy, hw, hh = self._config.head_rect
            desired_head_w = min(rect.width() * 0.63, rect.height() * 0.68, 780.0) * eased * pulse
            scale = desired_head_w / max(1.0, hw * cw)
            scale *= 1.0 + 0.08 * (1.0 - intro)
            draw_w = cw * scale
            draw_h = ch * scale
            draw_x = cx - (hx + hw / 2) * draw_w + shake_x
            draw_y = cy - (hy + hh / 2) * draw_h + shake_y
            painter.save()
            painter.translate(draw_x, draw_y)
            painter.scale(scale, scale)
            painter.drawPixmap(0, 0, self._head)
            painter.restore()

        # cartoon fire puffs at the bottom
        for i in range(12):
            phase = elapsed * 2.2 + i * 0.81
            bx = cx + math.sin(phase) * rect.width() * (0.17 + 0.035 * (i % 4))
            by = cy + rect.height() * (0.23 + 0.055 * (i % 5)) + math.cos(phase * 0.7) * 16
            radius = 18 + 25 * (0.5 + 0.5 * math.sin(phase * 1.3 + i))
            fire = QRadialGradient(QPointF(bx, by), radius)
            fire.setColorAt(0.0, QColor(255, 236, 163, 180))
            fire.setColorAt(0.45, QColor(255, 126, 70, 140))
            fire.setColorAt(1.0, QColor(195, 45, 55, 0))
            painter.setBrush(fire)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(bx, by), radius, radius * 0.8)

        # shake-proof giant headline
        big_font = font(52, QFont.Weight.Black)
        big_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        title = QPainterPath()
        fmetrics = QFontMetricsF(big_font)
        text = "你完了！！"
        text_w = fmetrics.horizontalAdvance(text)
        title.addText(QPointF(cx - text_w / 2 + shake_x * 0.45, rect.height() * 0.76), big_font, text)
        painter.setPen(QPen(QColor(46, 19, 25, 230), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QColor(255, 243, 205))
        painter.drawPath(title)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 243, 205))
        painter.drawPath(title)

        # the character's line in a little black speech strip
        line_font = font(20, QFont.Weight.DemiBold)
        painter.setFont(line_font)
        line_metrics = QFontMetricsF(line_font)
        line_text = line_metrics.elidedText(self._line, Qt.TextElideMode.ElideRight, rect.width() * 0.72)
        line_w = line_metrics.horizontalAdvance(line_text)
        strip = QRectF(cx - line_w / 2 - 28, rect.height() * 0.80, line_w + 56, 52)
        painter.setBrush(QColor(36, 22, 28, 215))
        painter.setPen(QPen(QColor(255, 209, 120, 180), 2))
        painter.drawRoundedRect(strip, 22, 22)
        painter.setPen(QColor(255, 247, 226))
        painter.drawText(strip, Qt.AlignmentFlag.AlignCenter, line_text)

        # small label
        painter.setFont(font(13, QFont.Weight.Medium))
        painter.setPen(QColor(255, 226, 190, 200))
        painter.drawText(
            QRectF(0, rect.height() - 74, rect.width(), 30),
            Qt.AlignmentFlag.AlignHCenter,
            f"{self._config.name} 正在暴走 · 可在托盘关闭「恶作剧模式」",
        )
        painter.end()


class StickyNote(QWidget):
    """A small auto-dismissing desktop note full of character sass."""

    COLORS = ("#FFF3B5", "#FFDCE1", "#DDF4E7", "#DDE7FF", "#FFE5C4")

    def __init__(self, text: str, config: CharacterConfig, position: QPoint, index: int = 0) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._text = text
        self._config = config
        self._index = index
        self._rotation = -3.5 + (index % 3) * 3.0
        self._colour = QColor(self.COLORS[index % len(self.COLORS)])
        self._border = QColor(self._colour).darker(126)
        self.setFixedSize(310, 176)
        self.move(position)
        self.setWindowOpacity(0.0)
        self._fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_in.setDuration(180)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_in.start()
        self._life = QTimer(self)
        self._life.setSingleShot(True)
        self._life.setInterval(4600)
        self._life.timeout.connect(self._fade_out)
        self._life.start()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _fade_out(self) -> None:
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(280)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade.finished.connect(self.close)
        self._fade.start()

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        self.close()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._rotation)
        painter.translate(-self.width() / 2, -self.height() / 2)
        body = QRectF(10, 13, self.width() - 21, self.height() - 23)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(42, 28, 31, 30))
        painter.drawRoundedRect(body.translated(3, 5), 8, 8)
        painter.setPen(QPen(self._border, 2))
        painter.setBrush(self._colour)
        painter.drawRoundedRect(body, 8, 8)
        # washi tape
        tape = QRectF(self.width() / 2 - 42, 5, 84, 23)
        painter.setBrush(QColor(255, 255, 255, 120))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(tape, 4, 4)
        # a little pin / heart
        painter.setBrush(QColor(self._config.accent))
        painter.setPen(QPen(self._border, 1.4))
        painter.drawEllipse(QPointF(self.width() / 2, 16), 7, 7)
        # text
        text_rect = QRectF(30, 39, self.width() - 60, self.height() - 70)
        painter.setPen(QColor("#4B3D3A"))
        text_font = font(12, QFont.Weight.Medium)
        painter.setFont(text_font)
        painter.drawText(
            text_rect,
            int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._text,
        )
        painter.setFont(font(9, QFont.Weight.Normal))
        painter.setPen(QColor(90, 76, 68, 150))
        painter.drawText(
            QRectF(30, self.height() - 34, self.width() - 60, 20),
            Qt.AlignmentFlag.AlignRight,
            f"— {self._config.name}  (点我撕掉)",
        )
        painter.end()


class MouseThief(QObject):
    """Briefly pulls the cursor towards the pet. Esc always aborts."""

    finished = pyqtSignal()

    def __init__(self, target_provider: Callable[[], QPoint] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._target_provider = target_provider
        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._step)
        self._clock = QElapsedTimer()
        self._duration = 0.0
        self._active = False
        self._allowed: Callable[[], bool] | None = None
        self._rng = random.Random(1234)

    def start(
        self,
        target_provider: Callable[[], QPoint],
        duration: float = 2.4,
        allowed: Callable[[], bool] | None = None,
    ) -> None:
        if self._active:
            return
        self._target_provider = target_provider
        self._allowed = allowed
        self._duration = max(0.6, duration)
        self._active = True
        self._clock.start()
        self._timer.start()

    @property
    def active(self) -> bool:
        return self._active

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        self.finished.emit()

    def _step(self) -> None:
        from PyQt6.QtGui import QCursor

        if not self._active:
            return
        if win32.escape_pressed() or (self._allowed is not None and not self._allowed()):
            self.stop()
            return
        elapsed = self._clock.elapsed() / 1000.0
        if elapsed >= self._duration:
            self.stop()
            return
        if not self._target_provider:
            self.stop()
            return
        current = QCursor.pos()
        target = self._target_provider()
        delta = target - current
        distance = math.hypot(delta.x(), delta.y())
        if distance > 4:
            # stronger pull near the end, as if the pet is tugging
            strength = 0.17 + 0.16 * (elapsed / self._duration)
            jitter = QPoint(self._rng.randint(-2, 2), self._rng.randint(-2, 2))
            next_pos = QPoint(
                int(round(current.x() + delta.x() * strength)) + jitter.x(),
                int(round(current.y() + delta.y() * strength)) + jitter.y(),
            )
            QCursor.setPos(next_pos)
