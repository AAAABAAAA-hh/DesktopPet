"""Foreground activity detection for the pets' reactions.

This intentionally only asks Windows which executable/title currently owns the
foreground window.  It does not enumerate unrelated process memory, read files,
or transmit anything.  Auto-watch can be disabled from the tray menu.
"""

from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from . import win32

log = logging.getLogger(__name__)

WORK_EXES = {
    "code.exe",
    "code - insiders.exe",
    "pycharm64.exe",
    "pycharm.exe",
    "idea64.exe",
    "idea.exe",
    "clion64.exe",
    "webstorm64.exe",
    "goland64.exe",
    "rider64.exe",
    "studio64.exe",
    "devecostudio64.exe",
    "sublime_text.exe",
    "notepad++.exe",
    "vim.exe",
    "gvim.exe",
    "emacs.exe",
    "winword.exe",
    "excel.exe",
    "powerpnt.exe",
    "wps.exe",
    "wpp.exe",
    "et.exe",
    "typora.exe",
    "obsidian.exe",
    "zotero.exe",
    "acrobat.exe",
    "acrord32.exe",
    "jupyter-notebook.exe",
    "rstudio.exe",
    "matlab.exe",
    "origin64.exe",
    "texstudio.exe",
    "overleaf.exe",
}

PLAY_EXES = {
    "steam.exe",
    "leagueclient.exe",
    "league of legends.exe",
    "valorant.exe",
    "cs2.exe",
    "csgo.exe",
    "dota2.exe",
    "genshinimpact.exe",
    "starrail.exe",
    "zenlesszonezero.exe",
    "minecraft.exe",
    "javaw.exe",
    "epicgameslauncher.exe",
    "wegame.exe",
    "battle.net.exe",
    "overwatch.exe",
    "r5apex.exe",
    "pubg.exe",
    "tslgame.exe",
    "gta5.exe",
    "rdr2.exe",
    "eldenring.exe",
    "hollow_knight.exe",
    "stardew valley.exe",
    "eu4.exe",
    "ck3.exe",
    "civilizationvi.exe",
}

BROWSERS = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "vivaldi.exe",
    "360se.exe",
    "qqbrowser.exe",
    "sogouexplorer.exe",
}

VIDEO_TITLE_WORDS = (
    "哔哩哔哩",
    "bilibili",
    "youtube",
    "腾讯视频",
    "爱奇艺",
    "优酷",
    "netflix",
    "抖音",
    "douyin",
    "twitch",
    "虎牙",
    "斗鱼",
    "直播",
    "在线观看",
    "视频",
)

GAME_TITLE_WORDS = (
    "原神",
    "崩坏",
    "星穹铁道",
    "绝区零",
    "英雄联盟",
    "league of legends",
    "valorant",
    "反恐精英",
    "cs2",
    "绝地求生",
    "我的世界",
    "minecraft",
    "dota",
    "apex",
    "守望先锋",
    "steam",
    "游戏",
)

WORK_TITLE_WORDS = (
    "visual studio code",
    "visual studio",
    "pycharm",
    "intellij",
    "webstorm",
    "clion",
    "goland",
    "jupyter",
    "python",
    "word",
    "excel",
    "powerpoint",
    "wps",
    "typora",
    "obsidian",
    "zotero",
    "overleaf",
    "texstudio",
    "matlab",
    "rstudio",
    "microsoft learn",
    "教程",
)


def classify_foreground(exe: str, title: str) -> str:
    """Return one of ``work``, ``play`` or ``other``."""

    exe = (exe or "").lower().strip()
    title = (title or "").lower().strip()
    if exe in WORK_EXES:
        return "work"
    if exe in PLAY_EXES:
        return "play"
    if exe in BROWSERS:
        if any(word in title for word in VIDEO_TITLE_WORDS):
            return "play"
        if any(word in title for word in WORK_TITLE_WORDS):
            return "work"
        return "other"
    if any(word in title for word in GAME_TITLE_WORDS):
        return "play"
    if any(word in title for word in WORK_TITLE_WORDS):
        return "work"
    return "other"


class ActivityWatcher(QObject):
    """Emit when the user settles into work or play for a few seconds."""

    activity_started = pyqtSignal(str)  # "work" / "play"
    category_changed = pyqtSignal(str)

    def __init__(self, interval_ms: int = 3500, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.interval_ms = max(1500, int(interval_ms))
        self._timer = QTimer(self)
        self._timer.setInterval(self.interval_ms)
        self._timer.timeout.connect(self._poll)
        self.last_category = "other"
        self._candidate = "other"
        self._candidate_count = 0
        self._primed = False
        self._running = False
        self._last_emit = 0.0

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running or not win32.IS_WINDOWS:
            return
        self._running = True
        self._primed = False
        self._candidate = "other"
        self._candidate_count = 0
        self._timer.start()
        QTimer.singleShot(400, self._poll)

    def stop(self) -> None:
        self._running = False
        self._timer.stop()

    def _poll(self) -> None:
        if not self._running:
            return
        exe, title = win32.foreground_info()
        category = classify_foreground(exe, title)
        if not self._primed:
            self._primed = True
            self.last_category = category
            self._candidate = category
            self._candidate_count = 0
            return

        if category == self.last_category:
            self._candidate = category
            self._candidate_count = 0
            return

        if category != self._candidate:
            self._candidate = category
            self._candidate_count = 1
            return
        self._candidate_count += 1
        if category in {"work", "play"} and self._candidate_count >= 2:
            now = time.monotonic()
            previous = self.last_category
            self.last_category = category
            self._candidate_count = 0
            if now - self._last_emit > 20.0 and previous != category:
                self._last_emit = now
                self.category_changed.emit(category)
                self.activity_started.emit(category)
        elif category == "other":
            self.last_category = "other"
            self._candidate_count = 0
