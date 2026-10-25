"""System tray icon and its context menu."""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from . import win32
from .manager import PetManager

log = logging.getLogger(__name__)


class TrayController:
    def __init__(self, manager: PetManager) -> None:
        self.manager = manager
        self.icon = QSystemTrayIcon(manager.common.icon)
        self.icon.setToolTip("桌角同学 Deskling")
        self.menu = QMenu()
        self.menu.setToolTipsVisible(True)
        self.icon.setContextMenu(self.menu)
        self.menu.aboutToShow.connect(self._rebuild_menu)
        self.icon.activated.connect(self._on_activated)
        self._visible = False

    def show(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("系统托盘不可用，桌宠仍可通过右键菜单操作")
            return
        self._rebuild_menu()
        self.icon.show()
        self._visible = True
        self.refresh_icon()

    def hide(self) -> None:
        self.icon.hide()
        self._visible = False

    def refresh_icon(self) -> None:
        active = self.manager.active_window
        if active is not None:
            self.icon.setIcon(self.manager.character_icon(active.config))
        else:
            self.icon.setIcon(self.manager.common.icon)
        self.refresh_tooltip()

    def refresh_tooltip(self) -> None:
        self.icon.setToolTip(self.manager.tooltip_text())

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.manager.toggle_visibility()

    # ------------------------------------------------------------------
    # menu construction
    # ------------------------------------------------------------------
    def _action(
        self,
        text: str,
        callback: Callable | None = None,
        *,
        checkable: bool = False,
        checked: bool = False,
        enabled: bool = True,
        icon: QIcon | None = None,
        tooltip: str = "",
        parent: QMenu | None = None,
    ) -> QAction:
        action = QAction(text, parent or self.menu)
        if icon is not None:
            action.setIcon(icon)
        if tooltip:
            action.setToolTip(tooltip)
        if checkable:
            action.setCheckable(True)
            action.setChecked(checked)
        action.setEnabled(enabled)
        if callback is not None:
            if checkable:
                action.toggled.connect(callback)
            else:
                action.triggered.connect(lambda _=False: callback())
        return action

    def _rebuild_menu(self) -> None:
        self.menu.clear()
        count = len(self.manager.windows)
        header = self._action(f"桌角同学 · 已召唤 {count} 位")
        header.setEnabled(False)
        self.menu.addAction(header)
        active = self.manager.active_window
        if active is not None:
            status = self._action(f"当前：{active.config.name} · {active.model.mood_label()}")
            status.setEnabled(False)
            self.menu.addAction(status)
        self.menu.addSeparator()

        if count:
            toggle_label = "收起所有桌宠" if self.manager.is_any_visible else "显示所有桌宠"
            self.menu.addAction(self._action(toggle_label, self.manager.toggle_visibility))
        else:
            self.menu.addAction(self._action("召唤一位同学", self.manager.start))
        self.menu.addAction(self._action("⚙️ 偏好设置…", self.manager.show_settings))

        summon_menu = QMenu("召唤同学到桌面", self.menu)
        summon_menu.setToolTipsVisible(True)
        if not self.manager.characters:
            empty = summon_menu.addAction("没有可用角色")
            empty.setEnabled(False)
        else:
            at_capacity = count >= self.manager.settings.max_pets
            for character in self.manager.characters:
                window = self.manager.window_for_slug(character.slug)
                if window is not None and window.isVisible():
                    label = f"收起 {character.name}"
                    action = QAction(self.manager.character_icon(character), label, summon_menu)
                    action.triggered.connect(
                        lambda _=False, w=window: self.manager.collapse_window(w)
                    )
                else:
                    label = f"显示 {character.name}" if window is not None else f"召唤 {character.name}"
                    action = QAction(self.manager.character_icon(character), label, summon_menu)
                    action.setEnabled(window is not None or not at_capacity)
                    if window is None and at_capacity:
                        action.setToolTip(f"最多同时召唤 {self.manager.settings.max_pets} 位")
                    action.triggered.connect(
                        lambda _=False, c=character: self.manager.summon_character(c)
                    )
                summon_menu.addAction(action)
        self.menu.addMenu(summon_menu)

        switch_menu = QMenu("切换宿主", self.menu)
        switch_menu.setToolTipsVisible(True)
        if count == 0:
            empty = switch_menu.addAction("桌面上还没有人")
            empty.setEnabled(False)
        else:
            current_slug = active.config.slug if active is not None else ""
            present_slugs = {window.config.slug for window in self.manager.windows}
            for character in self.manager.characters:
                suffix = "  · 已在桌面" if character.slug in present_slugs else ""
                action = QAction(
                    self.manager.character_icon(character),
                    f"{character.name}{suffix}",
                    switch_menu,
                )
                action.setCheckable(True)
                action.setChecked(character.slug == current_slug)
                action.triggered.connect(
                    lambda _=False, slug=character.slug: self.manager.switch_character(slug)
                )
                switch_menu.addAction(action)
        self.menu.addMenu(switch_menu)

        self.menu.addSeparator()

        feed_menu = QMenu("全员开饭", self.menu)
        feed_menu.setToolTipsVisible(True)
        if self.manager.catalog.foods:
            for food in self.manager.catalog.foods.values():
                action = QAction(self.manager.common.food_icon(food), food.name, feed_menu)
                action.setToolTip(f"{food.description}\n饱腹 +{int(food.hunger)}")
                action.triggered.connect(
                    lambda _=False, f=food: self.manager.feed_all(f)
                )
                feed_menu.addAction(action)
        else:
            action = feed_menu.addAction("没有可投喂的食物")
            action.setEnabled(False)
        self.menu.addMenu(feed_menu)

        pat = self._action("摸摸全员", self.manager.pat_all)
        pat.setEnabled(count > 0)
        self.menu.addAction(pat)
        sleep = self._action("全员睡觉", self.manager.sleep_all)
        sleep.setEnabled(count > 0)
        self.menu.addAction(sleep)
        wake = self._action("叫醒全员", self.manager.wake_all)
        wake.setEnabled(any(window.sleeping for window in self.manager.windows))
        self.menu.addAction(wake)

        self.menu.addSeparator()

        mischief = self._action(
            "恶作剧模式",
            self.manager.set_mischief_enabled,
            checkable=True,
            checked=self.manager.settings.mischief_enabled,
            tooltip="允许暴走时放大遮挡、贴纸条和抢鼠标。抢鼠标最多约 3 秒，按 Esc 可中断。",
        )
        self.menu.addAction(mischief)
        watch = self._action(
            "状态监听",
            self.manager.set_auto_watch_enabled,
            checkable=True,
            checked=self.manager.settings.auto_watch,
            enabled=win32.IS_WINDOWS,
            tooltip="只读取前台窗口的程序名和标题，用来说一句“又在摸鱼？”。不会读取内容或上传。",
        )
        self.menu.addAction(watch)
        sound = self._action(
            "音效",
            self.manager.set_sound_enabled,
            checkable=True,
            checked=self.manager.settings.sound_enabled,
        )
        self.menu.addAction(sound)
        self.menu.addSeparator()
        self.menu.addAction(self._action("使用说明", self.manager.show_help))
        self.menu.addAction(self._action("打开角色素材文件夹", self.manager.open_characters_folder))
        self.menu.addAction(self._action("完全退出程序", self.manager.quit_app))
        self.refresh_tooltip()
