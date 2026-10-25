"""Owns pet windows, content, menus and desktop-wide mischief."""

from __future__ import annotations

import json
import logging
import random
import shutil
import weakref
from pathlib import Path
from typing import Any, Callable, Iterable

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QAction, QGuiApplication, QIcon
from PyQt6.QtWidgets import QApplication, QMenu

from . import packager, win32
from .assets import CharacterAssets, CommonAssets, make_character_icon
from .audio import SoundPlayer
from .config import (
    Catalog,
    CharacterConfig,
    FoodItem,
    Settings,
    SYSTEM_CHARACTER_SLUGS,
    is_system_character,
    load_character,
)
from .effects import MouseThief, RageOverlay, StickyNote
from .paths import CHARACTERS_DIR, ICON_FILE, SOUNDS_DIR
from .ui import AboutDialog, SettingsDialog
from .watchers import ActivityWatcher
from .window import MAX_SCALE, MIN_SCALE, PetWindow

log = logging.getLogger(__name__)


class PetManager(QObject):
    def __init__(
        self,
        app: QApplication,
        characters: Iterable[CharacterConfig],
        catalog: Catalog,
        settings: Settings,
        settings_path: Path,
        *,
        characters_dir: Path = CHARACTERS_DIR,
        items_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.app = app
        self.characters = list(characters)
        self.by_slug = {character.slug: character for character in self.characters}
        self.catalog = catalog
        self.settings = settings
        self.settings_path = Path(settings_path)
        self.characters_dir = Path(characters_dir)
        self.items_dir = Path(items_dir) if items_dir else None
        self.common = CommonAssets(catalog, ICON_FILE)
        self.audio = SoundPlayer(SOUNDS_DIR, settings.sound_enabled)

        self._windows: list[PetWindow] = []
        self._active: PetWindow | None = None
        self._asset_cache: dict[str, CharacterAssets] = {}
        self._icon_cache: dict[str, QIcon] = {}
        self._settings_dialog: SettingsDialog | None = None
        self._tray: AnyTray | None = None
        self._notes: list[StickyNote] = []
        self._overlays: list[RageOverlay] = []
        self._effect_timers: list[QTimer] = []
        self._last_activity_reaction = 0.0
        self._closed = False
        self._rng = random.Random()

        self._mouse_thief = MouseThief(parent=self)
        self._watcher = ActivityWatcher(parent=self)
        self._watcher.activity_started.connect(self._on_activity)
        if settings.auto_watch:
            self._watcher.start()

    # ------------------------------------------------------------------
    # public-ish properties
    # ------------------------------------------------------------------
    @property
    def windows(self) -> list[PetWindow]:
        return list(self._windows)

    @property
    def active_window(self) -> PetWindow | None:
        if self._active is not None and self._active in self._windows:
            return self._active
        return self._windows[0] if self._windows else None

    @property
    def is_any_visible(self) -> bool:
        return any(window.isVisible() for window in self._windows)

    def has_character(self, slug: str) -> bool:
        return any(window.config.slug == slug for window in self._windows)

    def window_for_slug(self, slug: str) -> PetWindow | None:
        for window in self._windows:
            if window.config.slug == slug:
                return window
        return None

    def character_icon(self, config: CharacterConfig) -> QIcon:
        if config.slug not in self._icon_cache:
            self._icon_cache[config.slug] = make_character_icon(config, 96)
        return self._icon_cache[config.slug]

    # ------------------------------------------------------------------
    # startup / quit
    # ------------------------------------------------------------------
    def attach_tray(self, tray) -> None:
        self._tray = tray
        self._update_tray()

    def start(self) -> PetWindow | None:
        if self._windows:
            return self.active_window
        if not self.characters:
            log.error("没有可用角色")
            return None
        preferred = self.by_slug.get(self.settings.last_character)
        character = preferred or self.characters[0]
        return self.spawn(character)

    def quit_app(self) -> None:
        self.shutdown()
        self.app.quit()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._watcher.stop()
        self._mouse_thief.stop()
        self._clear_mischief()
        if self._settings_dialog is not None:
            try:
                self._settings_dialog.close()
            except Exception:
                pass
            self._settings_dialog = None
        for timer in self._effect_timers:
            timer.stop()
        for window in list(self._windows):
            window.dispose()
        self._windows.clear()
        self._active = None
        if self._tray is not None:
            try:
                self._tray.hide()
            except Exception:
                pass
        self.audio.stop()
        self.save_settings()

    def save_settings(self) -> None:
        try:
            self.settings.save(self.settings_path)
        except Exception:
            log.warning("保存设置失败", exc_info=True)

    # ------------------------------------------------------------------
    # window lifecycle
    # ------------------------------------------------------------------
    def _assets_for(self, character: CharacterConfig) -> CharacterAssets:
        if character.slug not in self._asset_cache:
            self._asset_cache[character.slug] = CharacterAssets(character, self.catalog, self.common)
        return self._asset_cache[character.slug]

    def _connect_window(self, window: PetWindow) -> None:
        window.activated.connect(self.activate)
        window.closed.connect(self._on_window_closed)
        window.rage_requested.connect(self._on_rage)
        window.stats_changed.connect(self._on_stats_changed)

    def spawn(
        self,
        character: CharacterConfig,
        *,
        position: QPoint | None = None,
        drop_in: bool = True,
        hint: bool = False,
    ) -> PetWindow | None:
        if self._closed:
            return None
        existing = self.window_for_slug(character.slug)
        if existing is not None:
            self.activate(existing)
            existing.say(self._rng.choice(["我在这儿呢。", "别召唤了，分身乏术。", "叫我干嘛？"]), priority=0)
            return existing
        if len(self._windows) >= self.settings.max_pets:
            active = self.active_window
            if active:
                active.say(
                    f"宿舍住不下啦！最多 {self.settings.max_pets} 个纸片人。",
                    priority=1,
                )
            return None

        first_ever = self.settings.first_run and not self._windows
        hint = hint or first_ever
        if position is None and self._windows:
            position = self._pick_spawn_position(character)
        assets = self._assets_for(character)
        window = PetWindow(
            self,
            character,
            self.catalog,
            assets,
            self.common,
            self.settings,
            position=position,
            hint=hint,
            drop_in=drop_in,
            scale=self.effective_scale(character),
        )
        self._connect_window(window)
        self._windows.append(window)
        self.activate(window)
        window.show()
        self.audio.sfx("summon")
        self.settings.last_character = character.slug
        if first_ever:
            self.settings.first_run = False
            self.save_settings()
        self._update_tray()
        return window

    def _pick_spawn_position(self, character: CharacterConfig) -> QPoint:
        screen = QGuiApplication.primaryScreen()
        active = self.active_window
        if active is not None:
            screen = QGuiApplication.screenAt(active.window_center()) or screen
        available = screen.availableGeometry() if screen else QRect(0, 0, 1200, 800)
        pet_w = round(character.canvas[0] * self.effective_scale(character)) + 52
        pet_h = round(character.canvas[1] * self.effective_scale(character)) + 129
        existing_centres = [window.window_center().x() for window in self._windows]
        fractions = (0.14, 0.34, 0.63, 0.86)
        candidates = [available.left() + int(available.width() * f) for f in fractions]
        if existing_centres:
            candidates.sort(key=lambda centre: min(abs(centre - other) for other in existing_centres), reverse=True)
        chosen = candidates[0]
        x = chosen - pet_w // 2
        x = max(available.left() - 30, min(available.right() - pet_w + 30, x))
        y = available.bottom() - pet_h - 2
        return QPoint(x, y)

    def activate(self, window: PetWindow) -> None:
        if window not in self._windows:
            return
        self._active = window
        window.raise_()
        if win32.IS_WINDOWS and window.isVisible():
            try:
                win32.place_topmost(int(window.winId()))
            except Exception:
                pass
        self._update_tray()

    def _on_window_closed(self, window: PetWindow) -> None:
        if self._closed:
            return
        if window in self._windows:
            self._windows.remove(window)
            window.deleteLater()
        if self._active is window:
            self._active = self._windows[0] if self._windows else None
        self._update_tray()

    def _dismiss_window(self, window: PetWindow) -> None:
        if window not in self._windows:
            return
        self._windows.remove(window)
        if self._active is window:
            self._active = self._windows[0] if self._windows else None
        window.dispose()
        self._update_tray()

    def open_characters_folder(self) -> None:
        self.open_folder(self.characters_dir)

    def switch_character(self, slug: str) -> None:
        if self._closed:
            return
        target = self.by_slug.get(slug)
        if target is None:
            return
        existing = self.window_for_slug(slug)
        if existing is not None:
            if not existing.isVisible():
                existing.show()
            self.activate(existing)
            existing.say("我在这儿，别把我切来切去的。", priority=1)
            return
        active = self.active_window
        if active is None:
            self.spawn(target)
            return
        screen = QGuiApplication.screenAt(active.window_center()) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QRect(0, 0, 1200, 800)
        new_w = round(target.canvas[0] * self.effective_scale(target)) + 52
        centre = active.x() + active.width() / 2
        x = int(centre - new_w / 2)
        x = max(available.left() - 20, min(available.right() - new_w + 20, x))
        y = active.y()
        self._dismiss_window(active)
        self.spawn(target, position=QPoint(x, y), hint=False, drop_in=True)

    @staticmethod
    def _posture_to_bust(posture: Any) -> bool | None:
        """Convert the settings dialog's posture choice into ``bust_mode``."""

        if posture is None:
            return None
        if isinstance(posture, bool):
            return posture
        key = str(posture).strip().lower()
        if key in {"sit", "sitting", "desk", "sit_desk", "坐姿", "坐姿趴桌", "趴桌"}:
            return True
        if key in {"stand", "standing", "站姿", "站立"}:
            return False
        return None

    def is_system_character(self, slug: str | CharacterConfig) -> bool:
        character = slug if isinstance(slug, CharacterConfig) else self.by_slug.get(str(slug))
        if character is None:
            return str(slug) in SYSTEM_CHARACTER_SLUGS
        return is_system_character(character)

    def can_delete_character(self, slug: str | CharacterConfig) -> bool:
        character = slug if isinstance(slug, CharacterConfig) else self.by_slug.get(str(slug))
        return character is not None and not is_system_character(character)

    def import_character(
        self,
        path: Path | str,
        *,
        name: str | None = None,
        subtitle: str | None = None,
        posture: Any = None,
        title: str | None = None,
        big_head: bool | None = None,
        head_scale: float = 1.4,
    ) -> tuple[bool, str, CharacterConfig | None]:
        """Create a new character from one uploaded image and use it now.

        ``name`` / ``subtitle`` / ``posture`` come from the import dialog;
        ``title`` is accepted as a friendly alias for ``subtitle``.
        When ``name`` is omitted (legacy callers and the CLI), the packager
        falls back to the image filename, but the settings UI always asks the
        user first so a custom character is never named ``IMG_2048`` by
        accident.
        """

        if self._closed:
            return False, "程序正在退出。", None
        if subtitle is None and title is not None:
            subtitle = title
        clean_name = None if name is None else str(name).strip()
        if name is not None and not clean_name:
            return False, "请先给这位同学起一个名字。", None
        clean_subtitle = None if subtitle is None else str(subtitle).strip()
        if subtitle is not None and not clean_subtitle:
            clean_subtitle = "自定义导入角色"
        bust_mode = self._posture_to_bust(posture)
        try:
            character = packager.package_character(
                Path(path),
                self.characters_dir,
                existing_slugs=set(self.by_slug),
                existing_names={c.name for c in self.characters},
                order=max((c.order for c in self.characters), default=0.0),
                name=clean_name,
                subtitle=clean_subtitle or "自定义导入角色",
                bust_mode=bust_mode,
                posture="sit" if bust_mode else ("stand" if bust_mode is False else None),
                big_head=big_head,
                head_scale=head_scale,
            )
        except Exception as exc:
            log.warning("导入角色失败：%s", exc)
            return False, f"导入失败：{exc}", None
        self.characters.append(character)
        self.by_slug[character.slug] = character
        self._icon_cache.pop(character.slug, None)
        if self.active_window is None:
            self.spawn(character)
        else:
            self.switch_character(character.slug)
        self._update_tray()
        message = f"已导入「{character.name}」，并切换为当前桌宠。"
        if character.cutout_method == "sticker":
            message += (
                " 本次使用了显式关闭 AI 的兼容路径；真人照片请安装 rembg/onnxruntime，"
                "默认会强制 AI 去底并拒绝生成贴纸。"
            )
        return True, message, character

    def update_character(
        self,
        slug: str,
        *,
        name: str | None = None,
        subtitle: str | None = None,
        posture: Any = None,
        title: str | None = None,
    ) -> tuple[bool, str]:
        """Edit a custom character's name / subtitle / posture in place.

        System classmates are intentionally locked, matching the delete lock.
        The folder name (slug) stays stable so tray/settings references and
        the on-disk folder do not churn when the display name changes.
        """

        character = self.by_slug.get(slug)
        if character is None:
            return False, "找不到这个角色。"
        if subtitle is None and title is not None:
            subtitle = title
        if character.is_system:
            return False, f"「{character.name}」是系统初始角色，信息已锁定。"

        config_file = character.folder / "config.json"
        try:
            raw = json.loads(config_file.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            log.warning("读取角色配置失败：%s", exc)
            return False, f"读取角色配置失败：{exc}"
        if not isinstance(raw, dict):
            return False, "角色配置格式不正确。"

        if name is not None:
            clean_name = str(name).strip()[:24]
            if not clean_name:
                return False, "角色名称不能为空。"
            duplicate = any(
                other.slug != slug and other.name == clean_name
                for other in self.characters
            )
            if duplicate:
                return False, f"已经有一位叫「{clean_name}」的同学了。"
            raw["name"] = clean_name
        if subtitle is not None:
            raw["subtitle"] = str(subtitle).strip()[:60] or "自定义导入角色"
        if posture is not None:
            bust_mode = self._posture_to_bust(posture)
            if bust_mode is None:
                return False, "未知的姿态类型。"
            raw["bust_mode"] = bust_mode
            raw["posture"] = "sit" if bust_mode else "stand"

        tmp = config_file.with_suffix(".json.tmp")
        try:
            original = config_file.read_text(encoding="utf-8")
        except OSError:
            original = ""
        try:
            tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(config_file)
            updated = load_character(character.folder)
        except Exception as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            if original:
                try:
                    config_file.write_text(original, encoding="utf-8")
                except OSError:
                    log.debug("回滚角色配置失败", exc_info=True)
            log.warning("保存角色信息失败：%s", exc)
            return False, f"保存角色信息失败：{exc}"

        self.characters = [updated if c.slug == slug else c for c in self.characters]
        self.characters.sort(key=lambda c: (c.order, c.name))
        self.by_slug[slug] = updated
        self._asset_cache.pop(slug, None)
        self._icon_cache.pop(slug, None)

        window = self.window_for_slug(slug)
        if window is not None:
            visible = window.isVisible()
            position = QPoint(window.x(), window.y())
            self._dismiss_window(window)
            if visible and not self._closed:
                self.spawn(updated, position=position, drop_in=False)
        self.save_settings()
        self._update_tray()
        return True, f"已更新「{updated.name}」的角色信息。"

    def delete_character(self, slug: str | CharacterConfig) -> tuple[bool, str]:
        """Remove a custom character folder and every reference to it.

        The four bundled classmates are locked.  Everything else is cleaned
        up in one action: open window, asset/icon caches, settings scale and
        ``last_character``, then the on-disk folder.
        """

        if self._closed:
            return False, "程序正在退出。"
        key = slug.slug if isinstance(slug, CharacterConfig) else str(slug)
        character = self.by_slug.get(key)
        if character is None:
            return False, "找不到这个角色。"
        if is_system_character(character):
            return False, f"「{character.name}」是系统初始角色，不能删除。"

        root = self.characters_dir.resolve()
        try:
            folder = character.folder.resolve()
        except OSError:
            folder = character.folder
        if folder.parent != root:
            return False, "只能删除角色目录内的自定义角色。"

        window = self.window_for_slug(key)
        had_window = window is not None
        window_position: QPoint | None = None
        window_visible = False
        if window is not None:
            window_position = QPoint(window.x(), window.y())
            window_visible = window.isVisible()
            self._dismiss_window(window)

        try:
            shutil.rmtree(folder)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("删除角色目录失败：%s", exc)
            if window_position is not None and window_visible and not self._closed:
                # The folder could not be removed, so put the pet back rather
                # than leaving the desktop one classmate short.
                self.spawn(character, position=window_position, drop_in=False)
            return False, f"删除角色目录失败：{exc}"

        self.characters = [c for c in self.characters if c.slug != key]
        self.by_slug.pop(key, None)
        self._asset_cache.pop(key, None)
        self._icon_cache.pop(key, None)
        self.settings.scales.pop(key, None)
        if self.settings.last_character == key:
            self.settings.last_character = self.characters[0].slug if self.characters else ""
        self.save_settings()

        if had_window and not self._windows and self.characters and not self._closed:
            self.spawn(self.characters[0], drop_in=False)
        self._update_tray()
        return True, f"已删除「{character.name}」，角色目录也已清理。"

    # Friendly alias for menu/shortcut code and older callers.
    remove_character = delete_character

    def summon_character(self, character: CharacterConfig) -> PetWindow | None:
        """Spawn another classmate (or bring a hidden one back)."""

        existing = self.window_for_slug(character.slug)
        if existing is not None:
            if not existing.isVisible():
                existing.show()
            existing.raise_()
            self.activate(existing)
            existing.say(self._rng.choice(["我回来了！", "叫我干嘛？", "这里还有位置。"]), priority=1)
            return existing
        return self.spawn(character)

    def collapse_window(self, window: PetWindow) -> None:
        """Hide one pet in the tray without destroying it."""

        if window not in self._windows:
            return
        window.hide()
        if self._active is window:
            self._active = next(
                (other for other in self._windows if other is not window and other.isVisible()),
                None,
            )
        self._update_tray()

    def toggle_visibility(self) -> None:
        if not self._windows:
            self.start()
            return
        if self.is_any_visible:
            for window in self._windows:
                window.hide()
        else:
            for window in self._windows:
                window.show()
                window.raise_()
            active = self.active_window
            if active:
                active.activate()
                active.say(
                    self._rng.choice(["我回来了！", "刚刚是不是想我了？", "休息够了，继续整活。"]),
                    priority=1,
                )
        self._update_tray()

    def show_all(self) -> None:
        for window in self._windows:
            if not window.isVisible():
                window.show()
            window.raise_()
        self._update_tray()

    def hide_all(self) -> None:
        for window in self._windows:
            window.hide()
        self._update_tray()

    # ------------------------------------------------------------------
    # mass actions
    # ------------------------------------------------------------------
    def feed_all(self, food: FoodItem) -> None:
        for window in self._windows:
            if window.isVisible():
                window.feed_item(food)

    def pat_all(self) -> None:
        for window in self._windows:
            if window.isVisible():
                window.pat(force=True, quiet=False)

    def sleep_all(self) -> None:
        for window in self._windows:
            window.sleep_now(auto=False)
        self.update_tooltip()

    def wake_all(self) -> None:
        for window in self._windows:
            if window.sleeping:
                window.wake_up(by_user=True)
        self.update_tooltip()

    # ------------------------------------------------------------------
    # preferences
    # ------------------------------------------------------------------
    def set_mischief_enabled(self, enabled: bool) -> None:
        self.settings.mischief_enabled = bool(enabled)
        if not enabled:
            self._clear_mischief()
        self.save_settings()
        self._update_tray()

    def set_auto_watch_enabled(self, enabled: bool) -> None:
        self.settings.auto_watch = bool(enabled)
        if enabled:
            self._watcher.start()
        else:
            self._watcher.stop()
        self.save_settings()
        self._update_tray()

    def set_sound_enabled(self, enabled: bool) -> None:
        self.settings.sound_enabled = bool(enabled)
        self.audio.set_enabled(enabled)
        self.save_settings()
        if enabled:
            self.audio.sfx("sparkle")
        self._update_tray()

    def set_max_pets(self, value: int) -> None:
        self.settings.max_pets = max(1, min(6, int(value)))
        self.save_settings()
        self._update_tray()

    def effective_scale(self, character: CharacterConfig) -> float:
        return self.settings.scale_for(character.slug, character.scale)

    def set_character_scale(self, slug: str, value: float) -> None:
        """Remember and immediately apply a display size for one character."""

        character = self.by_slug.get(slug)
        if character is None:
            return
        scale = max(MIN_SCALE, min(MAX_SCALE, float(value)))
        self.settings.scales[slug] = round(scale, 3)
        self.save_settings()
        window = self.window_for_slug(slug)
        if window is not None:
            window.set_scale(scale)

    # ------------------------------------------------------------------
    # foreground reactions
    # ------------------------------------------------------------------
    def _on_activity(self, category: str) -> None:
        if not self.settings.auto_watch:
            return
        import time as _time

        now = _time.monotonic()
        if now - self._last_activity_reaction < 70.0:
            return
        candidates = [w for w in self._windows if w.isVisible()]
        if not candidates:
            return
        target = self.active_window if self.active_window in candidates else candidates[0]
        target.react_to_activity(category)
        self._last_activity_reaction = now
        self.update_tooltip()

    # ------------------------------------------------------------------
    # mischief
    # ------------------------------------------------------------------
    def _on_rage(self, window: PetWindow, line: str) -> None:
        if not self.settings.mischief_enabled:
            return
        self.activate(window)
        screen = QGuiApplication.screenAt(window.window_center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        # One giant screaming face.
        for old in list(self._overlays):
            try:
                old.close()
            except Exception:
                pass
        head = window.composed_head("angry")
        overlay = RageOverlay(screen.geometry(), head, window.config, line, duration=3.05)
        overlay.finished.connect(lambda o=overlay: self._forget_overlay(o))
        self._overlays.append(overlay)
        overlay.start()

        self._schedule(420, lambda w=weakref.ref(window), l=line: self._show_rage_notes(w, l))
        self._schedule(920, lambda w=weakref.ref(window): self._start_mouse_theft(w))

    def _show_rage_notes(self, window_ref: weakref.ReferenceType, line: str) -> None:
        if not self.settings.mischief_enabled or self._closed:
            return
        window = window_ref()
        if window is None or not window.isVisible():
            return
        screen = QGuiApplication.screenAt(window.window_center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        lines = [
            line,
            "鼠标借我三秒，马上还。",
            "这就是戳我的下场。",
            "别找了，你的光标在我这儿。",
        ]
        chosen = [line] + self._rng.sample(lines[1:], 2)
        positions = [
            QPoint(available.left() + 36 + self._rng.randint(0, 24), available.top() + 40 + self._rng.randint(0, 24)),
            QPoint(
                max(available.left() + 20, available.right() - 340 - self._rng.randint(0, 30)),
                available.top() + available.height() // 3 + self._rng.randint(-20, 20),
            ),
            QPoint(
                available.left() + 70 + self._rng.randint(0, 30),
                max(available.top() + 30, available.bottom() - 220 - self._rng.randint(0, 30)),
            ),
        ]
        for i, (text, position) in enumerate(zip(chosen, positions)):
            note = StickyNote(text, window.config, position, index=i)
            note.destroyed.connect(lambda _=None, n=note: self._forget_note(n))
            self._notes.append(note)
            note.show()
            note.raise_()

    def _start_mouse_theft(self, window_ref: weakref.ReferenceType) -> None:
        if not self.settings.mischief_enabled or self._closed:
            return
        window = window_ref()
        if window is None or not window.isVisible():
            return

        def target():
            from PyQt6.QtGui import QCursor

            win = window_ref()
            if win is None:
                return QCursor.pos()
            try:
                return win.head_center_global()
            except RuntimeError:
                return QCursor.pos()

        def allowed() -> bool:
            if not self.settings.mischief_enabled:
                return False
            win = window_ref()
            if win is None:
                return False
            try:
                return win.isVisible()
            except RuntimeError:
                return False

        self._mouse_thief.start(target, duration=2.35, allowed=allowed)

    def _clear_mischief(self) -> None:
        try:
            self._mouse_thief.stop()
        except Exception:
            pass
        for overlay in list(self._overlays):
            try:
                overlay.close()
                overlay.deleteLater()
            except Exception:
                pass
        self._overlays.clear()
        for note in list(self._notes):
            try:
                note.close()
                note.deleteLater()
            except Exception:
                pass
        self._notes.clear()

    def _forget_note(self, note: StickyNote) -> None:
        if note in self._notes:
            self._notes.remove(note)

    def _forget_overlay(self, overlay: RageOverlay) -> None:
        if overlay in self._overlays:
            self._overlays.remove(overlay)
        overlay.deleteLater()

    def _schedule(self, delay_ms: int, callback: Callable[[], None]) -> None:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(max(0, delay_ms))

        def run() -> None:
            try:
                callback()
            finally:
                if timer in self._effect_timers:
                    self._effect_timers.remove(timer)
                timer.deleteLater()

        timer.timeout.connect(run)
        self._effect_timers.append(timer)
        timer.start()

    # ------------------------------------------------------------------
    # menus
    # ------------------------------------------------------------------
    def _style_menu(self, menu: QMenu) -> QMenu:
        menu.setToolTipsVisible(True)
        menu.setFont(menu.font())
        return menu

    def add_food_actions(self, menu: QMenu, callback: Callable[[FoodItem], None]) -> None:
        for food in self.catalog.foods.values():
            action = QAction(self.common.food_icon(food), food.name, menu)
            action.setToolTip(
                f"{food.description}\n饱腹 +{int(food.hunger)} · 电量 {int(food.energy):+d}"
                + (f" · 火气 +{int(food.anger)}" if food.anger else "")
            )
            action.triggered.connect(lambda _=False, f=food: callback(f))
            menu.addAction(action)
        if not self.catalog.foods:
            action = menu.addAction("没有可投喂的食物")
            action.setEnabled(False)

    def add_wardrobe_actions(self, menu: QMenu, window: PetWindow) -> None:
        """Small accessories only: head_top / face / hand.

        There is deliberately no clothing category and no torso mount, so a
        catalogue item can never be stretched across an arbitrary silhouette.
        Custom characters without ``costumes/`` get no wardrobe entry at all.
        """

        if not window.config.has_costumes:
            return
        for category, items in self.catalog.categories():
            if not items:
                continue
            submenu = self._style_menu(menu.addMenu(category))
            for item in items:
                if not item.is_accessory:
                    continue
                action = QAction(item.name, submenu)
                action.setCheckable(True)
                action.setChecked(item.id in window.accessories)
                action.setToolTip(item.description)
                action.triggered.connect(
                    lambda _=False, w=window, i=item: w.toggle_wardrobe(i)
                )
                submenu.addAction(action)
        if window.accessories:
            menu.addSeparator()
            reset = menu.addAction("取下所有挂件")
            reset.triggered.connect(lambda _=False, w=window: w.clear_wardrobe())

    def build_context_menu(self, window: PetWindow) -> QMenu:
        menu = self._style_menu(QMenu())
        header = QAction(self.character_icon(window.config), f"{window.config.name} · {window.config.subtitle}", menu)
        header.setEnabled(False)
        menu.addAction(header)
        status = menu.addAction(f"   {window.model.stat_line()}")
        status.setEnabled(False)
        menu.addSeparator()

        pat = menu.addAction("摸摸头（滚轮也能摸）")
        pat.triggered.connect(lambda _=False, w=window: w.pat(force=True))

        feed_menu = self._style_menu(menu.addMenu("投喂"))
        self.add_food_actions(feed_menu, window.feed_item)

        if window.config.has_costumes:
            wardrobe_menu = self._style_menu(menu.addMenu("换装"))
            self.add_wardrobe_actions(wardrobe_menu, window)

        switch_menu = self._style_menu(menu.addMenu("更换人物模型"))
        for character in self.characters:
            present_here = window.config.slug == character.slug
            action = QAction(
                self.character_icon(character),
                f"{character.name} · {character.subtitle}" + ("（当前）" if present_here else ""),
                switch_menu,
            )
            action.setCheckable(True)
            action.setChecked(present_here)
            action.setToolTip(
                f"把当前同学换成{character.name}"
                if not self.has_character(character.slug)
                else f"切换到桌面上的{character.name}"
            )
            action.triggered.connect(
                lambda _=False, slug=character.slug: QTimer.singleShot(
                    40, lambda: self.switch_character(slug)
                )
            )
            switch_menu.addAction(action)

        summon_menu = self._style_menu(menu.addMenu("➕ 召唤同学到桌面"))
        for character in self.characters:
            existing = self.window_for_slug(character.slug)
            if existing is not None and existing.isVisible():
                # Clicking an already summoned classmate puts it back in the
                # tray, so the same menu item toggles "summon / dismiss".
                label = f"收起 {character.name}"
                action = QAction(self.character_icon(character), label, summon_menu)
                action.setToolTip("再点一次就把这位同学收起至托盘。")
                action.triggered.connect(
                    lambda _=False, w=existing: QTimer.singleShot(
                        0, lambda: self.collapse_window(w)
                    )
                )
            else:
                at_limit = existing is None and len(self._windows) >= self.settings.max_pets
                label = f"显示 {character.name}" if existing is not None else f"召唤 {character.name}"
                if at_limit:
                    label = f"{character.name}（已达上限）"
                action = QAction(self.character_icon(character), label, summon_menu)
                action.setEnabled(not at_limit)
                action.triggered.connect(
                    lambda _=False, c=character: QTimer.singleShot(
                        0, lambda: self.summon_character(c)
                    )
                )
            summon_menu.addAction(action)
        menu.addSeparator()

        if window.sleeping:
            sleep = menu.addAction("叫醒它")
            sleep.triggered.connect(lambda _=False, w=window: w.wake_up(by_user=True))
        else:
            sleep = menu.addAction("哄它睡觉")
            sleep.triggered.connect(lambda _=False, w=window: w.sleep_now(auto=False))

        if window.mode == "study":
            study = menu.addAction("下课，别学了")
            study.triggered.connect(lambda _=False, w=window: w.stop_studying())
        else:
            study = menu.addAction("陪我学习 30 秒")
            study.triggered.connect(lambda _=False, w=window: w.study_now())
            if window.sleeping:
                study.setEnabled(False)

        rage_label = "让它暴走"
        if window.model.rage_cooldown > 0:
            rage_label = f"还在消气（{int(window.model.rage_cooldown)} 秒）"
        rage = menu.addAction(rage_label)
        rage.setEnabled(window.model.rage_cooldown <= 0 and not window.sleeping)
        rage.triggered.connect(lambda _=False, w=window: w.force_rage(manual=True))
        menu.addSeparator()

        settings = menu.addAction("⚙️ 偏好设置…")
        settings.triggered.connect(lambda _=False: QTimer.singleShot(0, self.show_settings))
        folder = menu.addAction("打开角色素材文件夹")
        folder.triggered.connect(lambda _=False, c=window.config: self.open_folder(c.folder))
        collapse = menu.addAction("收起至托盘")
        collapse.setToolTip("把这个同学藏到托盘里，之后可以再次召唤。")
        collapse.triggered.connect(lambda _=False, w=window: self.collapse_window(w))
        menu.addSeparator()
        quit_action = menu.addAction("完全退出程序")
        quit_action.setToolTip("关闭所有桌宠和托盘图标。")
        quit_action.triggered.connect(self.quit_app)
        return menu

    def open_folder(self, path: Path) -> None:
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception:
            log.warning("打开文件夹失败：%s", path, exc_info=True)

    def show_help(self) -> None:
        dialog = AboutDialog(parent=None, open_folder_callback=lambda: self.open_folder(self.characters_dir))
        dialog.setWindowIcon(self.common.icon)
        active = self.active_window
        if active is not None:
            dialog.set_avatar(self.character_icon(active.config).pixmap(96, 96))
        dialog.raise_()
        dialog.activateWindow()
        dialog.exec()

    def show_settings(self) -> None:
        """Open the settings panel after the menu that invoked it has closed."""

        if self._closed:
            return
        if self._settings_dialog is not None:
            try:
                self._settings_dialog.show()
                self._settings_dialog.raise_()
                self._settings_dialog.activateWindow()
            except RuntimeError:
                self._settings_dialog = None
            return
        QTimer.singleShot(0, self._open_settings)

    def _open_settings(self) -> None:
        if self._closed or self._settings_dialog is not None:
            return
        dialog = SettingsDialog(self)
        # Settings is deliberately non-modal: pets keep roaming, can be
        # dragged, petted and fed while the panel is open.
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.finished.connect(lambda _result=0, d=dialog: self._settings_closed(d))
        self._settings_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self._update_tray()

    def _settings_closed(self, dialog: SettingsDialog) -> None:
        if self._settings_dialog is dialog:
            self._settings_dialog = None
        self._update_tray()

    # ------------------------------------------------------------------
    # tray bridge
    # ------------------------------------------------------------------
    def tooltip_text(self) -> str:
        if not self._windows:
            return "桌角同学 · 桌面空空如也"
        active = self.active_window
        if active is None:
            return f"桌角同学 · 已召唤 {len(self._windows)} 位"
        text = f"{active.config.name}：{active.model.mood_label()} · 火气 {int(active.model.anger)}%"
        if len(self._windows) > 1:
            text += f" · 共 {len(self._windows)} 位"
        return text

    def update_tooltip(self) -> None:
        if self._tray is not None:
            try:
                self._tray.refresh_tooltip()
            except Exception:
                log.debug("刷新托盘失败", exc_info=True)

    def _update_tray(self) -> None:
        self.update_tooltip()
        if self._tray is not None:
            try:
                self._tray.refresh_icon()
            except Exception:
                log.debug("刷新托盘图标失败", exc_info=True)

    def _on_stats_changed(self, window: PetWindow) -> None:
        if self.active_window is window:
            self.update_tooltip()


# Small forward-declaration helper so attach_tray can be typed without a cycle.
AnyTray = object
