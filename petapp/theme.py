"""Shared visual language: fonts, colours and QSS."""

from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

INK = "#3B3340"
MUTED = "#8B7C70"
PAPER = "#FFFDF8"
CREAM = "#F7F0E5"
LINE = "#E5D8C7"
ACCENT = "#7B68EE"
WARM = "#FFB86B"
DANGER = "#D95C62"
FONT_STACK = ["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", "sans-serif"]
EMOJI_STACK = ["Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", "Segoe UI Symbol"]


def pick_font_family() -> str:
    available = set(QFontDatabase.families())
    for family in FONT_STACK:
        if family in available:
            return family
    return QApplication.font().family()


def pick_emoji_family() -> str:
    available = set(QFontDatabase.families())
    for family in EMOJI_STACK:
        if family in available:
            return family
    return pick_font_family()


def font(size: float = 10.0, weight: QFont.Weight = QFont.Weight.Normal, italic: bool = False) -> QFont:
    f = QFont(pick_font_family(), int(size))
    f.setWeight(weight)
    f.setItalic(italic)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def emoji_font(pixel_size: int) -> QFont:
    """A font with colour emoji support, sized in device-independent pixels."""

    f = QFont(pick_emoji_family())
    f.setPixelSize(max(8, int(pixel_size)))
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def color(value: str, alpha: int | None = None) -> QColor:
    c = QColor(value)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


APP_QSS = f"""
QMenu {{
    background: {PAPER};
    border: 1px solid {LINE};
    border-radius: 12px;
    padding: 7px;
    color: {INK};
}}
QMenu::item {{
    padding: 6px 26px 6px 28px;
    border-radius: 7px;
    min-width: 170px;
}}
QMenu::item:selected {{
    background: #EEE8FF;
    color: {INK};
}}
QMenu::item:disabled {{
    color: {MUTED};
    background: transparent;
}}
QMenu::separator {{
    height: 1px;
    background: {LINE};
    margin: 5px 10px;
}}
QMenu::icon {{
    padding-left: 8px;
}}
QMenu::indicator {{
    width: 13px;
    height: 13px;
    border-radius: 4px;
    border: 1px solid #CFC2B2;
    background: #FFFFFF;
    margin-left: 8px;
}}
QMenu::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}

QDialog {{
    background: {CREAM};
}}
QToolTip {{
    background: {PAPER};
    color: {INK};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 5px 8px;
}}
QPushButton {{
    background: {PAPER};
    color: {INK};
    border: 1px solid {LINE};
    border-radius: 9px;
    padding: 7px 14px;
}}
QPushButton:hover {{
    background: #FFF6E9;
    border-color: #D9C6AE;
}}
QPushButton:pressed {{
    background: #F4ECDF;
}}
QPushButton#primary {{
    background: {ACCENT};
    color: white;
    border: 1px solid {ACCENT};
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: #8B79F4;
}}
QLabel {{
    color: {INK};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #D8CBBB;
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0px 2px;
}}
QScrollBar::handle:horizontal {{
    background: #D8CBBB;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

QFrame#settingsSection {{
    background: {PAPER};
    border: 1px solid #EADFD0;
    border-radius: 16px;
}}
QScrollArea#cardScroll {{
    border: none;
    background: transparent;
}}
QWidget#cardsHost {{
    background: transparent;
}}
QScrollArea#settingsPage {{
    border: none;
    background: transparent;
}}
QWidget#settingsPageBody {{
    background: transparent;
}}
QListWidget#settingsNav {{
    background: transparent;
    border: none;
    outline: 0;
    padding: 2px;
}}
QListWidget#settingsNav::item {{
    height: 40px;
    padding-left: 14px;
    margin: 2px 0px;
    border-radius: 10px;
    color: #6E6054;
}}
QListWidget#settingsNav::item:hover {{
    background: #FFF7ED;
}}
QListWidget#settingsNav::item:selected {{
    background: #F1EDFF;
    color: {INK};
    font-weight: 600;
    border-left: 3px solid {ACCENT};
    padding-left: 11px;
}}
QFrame#settingsDivider {{
    color: #EADFD0;
    background: #EADFD0;
    border: none;
    max-height: 1px;
}}
QToolButton#characterCard {{
    background: #FFFEFA;
    border: 1px solid #E5D8C7;
    border-radius: 14px;
    padding: 8px 5px;
    color: #5B4C43;
}}
QToolButton#characterCard:hover {{
    background: #FFF7ED;
    border-color: #D7C2A4;
}}
QToolButton#characterCard:checked {{
    background: #F1EDFF;
    border: 2px solid {ACCENT};
    color: {INK};
}}
QToolButton#deleteCharacterCard {{
    background: transparent;
    border: none;
    border-radius: 9px;
    color: #B08F86;
    font-size: 10px;
    padding: 0px;
}}
QToolButton#deleteCharacterCard:hover {{
    background: #FBE3E1;
    color: {DANGER};
}}
QToolButton#deleteCharacterCard:disabled {{
    color: #C9BFB4;
    background: transparent;
}}
QToolButton#importCard {{
    background: #FBF8FF;
    border: 1px dashed #B9A8F5;
    border-radius: 14px;
    color: #6A57D8;
    padding: 5px;
}}
QToolButton#importCard:hover {{
    background: #F1EDFF;
    border-color: {ACCENT};
}}
QCheckBox {{
    color: {INK};
    spacing: 8px;
}}
QSpinBox {{
    background: {PAPER};
    color: {INK};
    border: 1px solid {LINE};
    border-radius: 8px;
    padding: 5px 8px;
    min-width: 66px;
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: #EFE3D3;
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: #FFFFFF;
    border: 2px solid {ACCENT};
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{
    background: #FFF7ED;
}}
QSlider:disabled {{
    color: #C9BFB4;
}}
QLabel#muted {{
    color: {MUTED};
}}
QLabel#settingsTitle {{
    color: {INK};
}}
"""


def apply_app_style(app: QApplication) -> None:
    app.setStyleSheet(APP_QSS)
    app.setFont(font(10))
