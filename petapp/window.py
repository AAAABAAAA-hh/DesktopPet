"""The transparent, always-on-top desktop pet window."""

from __future__ import annotations

import logging
import math
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PyQt6.QtCore import QFileInfo, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PyQt6.QtWidgets import QApplication, QFileIconProvider, QWidget

from . import win32
from .assets import CharacterAssets, CommonAssets
from .audio import SoundPlayer
from .config import (
    MAX_SCALE,
    MIN_SCALE,
    Catalog,
    CharacterConfig,
    FoodItem,
    Settings,
    WardrobeItem,
)
from .engine import ROAM_SPEED, AutonomousEngine, WanderDecision
from .model import Activity, Expression, PetModel
from .motion import BounceHop, ClickCombo, HopSample, TapBounce
from .rig import RagdollRig, RigPose
from .theme import emoji_font, font

log = logging.getLogger(__name__)

FOOT_GAP = 2.0
MAX_PARTICLES = 80

# Speech bubble timing.  A comic bubble stays fully readable for
# ``BUBBLE_HOLD`` seconds and then fades out over ``BUBBLE_FADE`` seconds.
BUBBLE_HOLD = 2.5
BUBBLE_FADE = 0.4

# Anger is grouped into bands; crossing into a new one deserves a comment.
ANGER_BANDS = 4.0


@dataclass
class Bubble:
    text: str
    born: float
    hold_until: float
    expires: float
    priority: int = 1
    voice: str = ""

    def alpha(self, now: float) -> float:
        if now <= self.hold_until:
            return 1.0
        remaining = self.expires - now
        if remaining <= 0:
            return 0.0
        return max(0.0, min(1.0, remaining / BUBBLE_FADE))


@dataclass
class Particle:
    kind: str
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    size: float
    colour: QColor
    gravity: float = 0.0
    text: str = ""
    phase: float = 0.0


class PetWindow(QWidget):
    """One independently living paper classmate."""

    activated = pyqtSignal(object)
    closed = pyqtSignal(object)
    rage_requested = pyqtSignal(object, str)
    stats_changed = pyqtSignal(object)

    def __init__(
        self,
        manager: Any,
        config: CharacterConfig,
        catalog: Catalog,
        assets: CharacterAssets,
        common: CommonAssets,
        settings: Settings,
        *,
        position: QPoint | None = None,
        hint: bool = False,
        drop_in: bool = True,
        scale: float | None = None,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.manager = manager
        self.config = config
        self.catalog = catalog
        self.assets = assets
        self.common = common
        self.settings = settings
        self.audio: SoundPlayer | None = getattr(manager, "audio", None)
        self.model = PetModel(config, random.Random())
        self._rng = random.Random()
        # Pure-Python main behaviour timer: 8–15 s between autonomous choices.
        self._autonomy = AutonomousEngine(self._rng)
        self._rig = RagdollRig(
            config.order + config.scale,
            profile=config.motion,
            canvas=config.canvas,
        )
        self._rig_pose: RigPose = self._rig.pose

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setWindowTitle(f"{config.name} · 桌角同学")
        self.setWindowIcon(common.icon)
        self.setToolTip(
            f"{config.name} · {config.subtitle}\n"
            "左键拖动 / 戳脸 · 滚轮摸头 · 右键菜单\n"
            "可以把文件拖到它脸上投喂"
        )

        self._scale = float(config.scale if scale is None else scale)
        self._scale = max(MIN_SCALE, min(MAX_SCALE, self._scale))
        self._bust_mode = bool(config.bust_mode)
        self._cw, self._ch = config.canvas
        self._pet_w = max(1, round(self._cw * self._scale))
        self._pet_h = max(1, round(self._ch * self._scale))
        self._side = 26
        self._top_space = 124
        self._paint_w = self._pet_w + self._side * 2
        self._paint_h = self._pet_h + self._top_space + 5
        self.setFixedSize(self._paint_w, self._paint_h)

        now = time.monotonic()
        self._last_tick = now
        self._mode = Activity.IDLE.value
        self._mode_started = now
        self._x = 0.0
        self._y = 0.0
        self._vx = 0.0
        self._vy = 0.0
        self._direction = self._rng.choice((-1, 1))
        self._facing = self._direction
        self._walk_speed = ROAM_SPEED
        self._walk_until = now
        self._hop = BounceHop()
        self._hop_cycle_started = now
        self._hop_start_x = 0.0
        self._hop_distance = 0.0
        self._hop_y = 0.0
        self._hop_scale_x = 1.0
        self._hop_scale_y = 1.0
        self._next_decision = now + self._autonomy.next_delay()
        self._sit_until = 0.0
        # Small in-place "doodle" used while standing idle.
        self._idle_tilt_angle = 0.0
        self._idle_tilt_until = 0.0
        self._next_chatter = now + self._rng.uniform(28.0, 50.0)
        self._next_hunger = now + self._rng.uniform(12.0, 25.0)
        self._next_blink = now + self._rng.uniform(
            config.motion.blink_interval_min, config.motion.blink_interval_max
        )
        self._blink_until = 0.0
        motion = config.motion
        self._tap_bounce = TapBounce(
            duration=motion.tap_duration,
            width=motion.tap_width,
            height=motion.tap_height,
        )
        self._head_inertia = 0.0
        self._head_inertia_v = 0.0
        self._resting_sit = False
        self._click_combo = ClickCombo(
            threshold=motion.combo_threshold,
            window=motion.combo_window,
            cooldown=motion.combo_cooldown,
        )
        self._combo_mark_born = 0.0
        self._combo_mark_until = 0.0
        self._combo_angry_until = 0.0
        self._pat_cooldown = 0.0
        self._pat_count = 0
        self._eat_started = now
        self._eat_end = now
        self._food_pixmap: QPixmap | None = None
        self._food_item: FoodItem | None = None
        self._crumbing_done = False
        self._study_end = 0.0
        self._sleep_started = 0.0
        self._next_zzz = 0.0
        self._rage_started = 0.0
        self._rage_end = 0.0
        self._rage_emit_at: float | None = None
        self._rage_emit_line = ""
        self._rage_pending_at: float | None = None
        self._climb_side = 0
        self._climb_started = 0.0
        self._climb_until = 0.0
        self._next_climb_allowed = now + 8.0
        self._landed_from_drag = False
        self._fall_bounces = 0
        self._greet_due: float | None = now + (1.3 if drop_in else 0.6)
        self._hint_due: float | None = None
        self._hint_enabled = bool(hint)
        self._greeted = False
        self._interacted = False
        self._bubble: Bubble | None = None
        self._particles: list[Particle] = []
        self._drop_hover = False
        self._pressed = False
        self._press_global = QPointF()
        self._press_local = QPointF()
        self._drag_offset = QPointF()
        self._dragging = False
        self._drag_samples: list[tuple[float, QPointF]] = []
        # Smoothed pointer velocity, used by the ragdoll instead of the raw
        # screen position delta (mouse events arrive in bursts).
        self._pointer_vx = 0.0
        self._pointer_vy = 0.0
        self._last_pointer_pos = QPointF()
        self._last_pointer_time = now
        self._woke_on_press = False
        self._menu_open = False
        self._hover = False
        self._hwnd = 0
        self._pass_through = False
        self._native_configured = False
        self._closing_silently = False
        self._last_bubble_line = ""
        self._anger_band = int(self.model.anger // (100.0 / ANGER_BANDS))
        # Ambient "held" sweat drop.  It lives outside the face texture; the
        # original head.png is never painted over.
        self._sweat_alpha = 0.0
        self._sweat_target = 0.0
        self._sweat_visible = False
        # Optional external Godot renderer (engine/bridge.py).  None keeps the
        # normal PyQt render path; no Godot executable is required.
        self._godot_bridge: Any | None = None

        # Wardrobe is accessory-only now: head_top / face / hand.  There is no
        # torso/outfit overlay that could land as a stray rectangle on art
        # whose silhouette is not the standard paper-doll shape.
        self._accessories: tuple[str, ...] = (
            self._normalise_accessories(config.starting_accessories[::1])
            if config.has_costumes
            else ()
        )

        # place at the requested spot, otherwise on the primary work area
        if position is None:
            screen = QGuiApplication.primaryScreen()
            available = screen.availableGeometry() if screen else QRect(0, 0, 1200, 800)
            x = available.right() - self._paint_w + self._side - round(self._pet_w * 0.05) - 8
            y = available.bottom() - FOOT_GAP - (self._top_space + self._pet_h)
        else:
            x = position.x()
            y = position.y()
        self._x = float(x)
        self._y = float(y)
        self._snap_x()
        ground = self._ground_window_y()
        if drop_in:
            self._y = ground - 155.0
            self._vy = 0.0
            self._set_mode(Activity.FALL.value)
        else:
            self._y = ground
            self._set_mode(Activity.IDLE.value)
        self.move(round(self._x), round(self._y))

        self._ticker = QTimer(self)
        self._ticker.setInterval(33)
        self._ticker.timeout.connect(self._tick)
        self._click_timer = QTimer(self)
        self._click_timer.setInterval(42)
        self._click_timer.timeout.connect(self._poll_click_through)
        self._started = False
        QTimer.singleShot(0, self._maybe_auto_godot)

    # ------------------------------------------------------------------
    # basic properties
    # ------------------------------------------------------------------
    @property
    def display_name(self) -> str:
        return self.config.name

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def sleeping(self) -> bool:
        return self._mode == Activity.SLEEP.value

    @property
    def busy(self) -> bool:
        return self._mode in {Activity.DRAG.value, Activity.FALL.value, Activity.RAGE.value}

    @property
    def scale(self) -> float:
        return self._scale

    @property
    def accessories(self) -> tuple[str, ...]:
        return self._accessories

    @property
    def rig_pose(self) -> RigPose:
        return self._rig_pose

    def composed_head(self, expression: str = "normal") -> QPixmap:
        return self.assets.compose_head(expression, self._accessories)

    def window_center(self) -> QPoint:
        return QPoint(self.x() + self.width() // 2, self.y() + self.height() // 2)

    def head_center_global(self) -> QPoint:
        hx, hy, hw, hh = self.config.head_rect
        x = self.x() + self._side + hx * self._pet_w + hw * self._pet_w / 2
        y = self.y() + self._top_space + hy * self._pet_h + hh * self._pet_h * 0.54
        return QPoint(round(x), round(y))

    def status_summary(self) -> str:
        return f"{self.config.name} · {self.model.stat_line()}"

    def is_visible(self) -> bool:
        return self.isVisible()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        super().showEvent(event)
        if not self._started:
            self._started = True
        self._last_tick = time.monotonic()
        self._ticker.start()
        self._click_timer.start()
        QTimer.singleShot(0, self._configure_native_window)
        if self._greet_due is None and not self._greeted:
            self._greet_due = time.monotonic() + 0.7
        self.raise_()

    def hideEvent(self, event) -> None:  # noqa: N802, ANN001
        self._ticker.stop()
        self._click_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        self._ticker.stop()
        self._click_timer.stop()
        if self._hwnd and win32.IS_WINDOWS:
            win32.set_click_through(self._hwnd, False)
        super().closeEvent(event)
        if not self._closing_silently:
            self.closed.emit(self)

    def dispose(self) -> None:
        self._closing_silently = True
        if self._godot_bridge is not None:
            try:
                self._godot_bridge.stop()
            except Exception:
                log.debug("Godot renderer shutdown failed", exc_info=True)
            self._godot_bridge = None
        self._ticker.stop()
        self._click_timer.stop()
        self.hide()
        self.close()
        self.deleteLater()

    def _configure_native_window(self) -> None:
        if self._native_configured:
            return
        self._native_configured = True
        if not win32.IS_WINDOWS:
            return
        try:
            self._hwnd = win32.pet_window_handle(self)
            if self._hwnd:
                win32.style_pet_window(self._hwnd)
                self._poll_click_through(initial=True)
        except Exception as exc:
            log.debug("native setup failed: %s", exc)

    # ------------------------------------------------------------------
    # geometry helpers
    # ------------------------------------------------------------------
    def _current_screen_rect(self) -> QRect:
        center = QPoint(self.x() + self.width() // 2, self.y() + self.height() // 2)
        screen = QGuiApplication.screenAt(center)
        if screen is None:
            feet = QPoint(self.x() + self.width() // 2, self.y() + self.height() - 30)
            screen = QGuiApplication.screenAt(feet)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen else QRect(0, 0, 1200, 800)

    def _ground_window_y(self) -> float:
        return float(self._current_screen_rect().bottom() - FOOT_GAP - (self._top_space + self._pet_h))

    def _body_edges(self, x: float | None = None) -> tuple[float, float]:
        x = self._x if x is None else x
        left = x + self._side + self._pet_w * 0.075
        right = x + self._side + self._pet_w * 0.925
        return left, right

    def _snap_x(self) -> None:
        rect = self._current_screen_rect()
        left_edge, right_edge = self._body_edges(self._x)
        if left_edge < rect.left():
            self._x += rect.left() - left_edge
        elif right_edge > rect.right():
            self._x -= right_edge - rect.right()

    def _clamp_drag_position(self, x: float, y: float) -> tuple[float, float]:
        rect = self._current_screen_rect()
        min_x = rect.left() - self.width() * 0.45
        max_x = rect.right() - self.width() * 0.55
        min_y = rect.top() - 70
        max_y = rect.bottom() - 110
        return (max(min_x, min(max_x, x)), max(min_y, min(max_y, y)))

    def _at_floor(self, tolerance: float = 2.5) -> bool:
        return abs(self._y - self._ground_window_y()) <= tolerance

    def _set_grounded(self) -> None:
        self._y = self._ground_window_y()
        self._vy = 0.0
        self._vx = 0.0
        self.move(round(self._x), round(self._y))

    def set_scale(self, scale: float) -> None:
        """Resize the whole pet, keeping its feet on the same spot."""

        scale = max(MIN_SCALE, min(MAX_SCALE, float(scale)))
        if abs(scale - self._scale) < 0.001:
            return
        feet_x = self._x + self._side + self._pet_w / 2
        self._scale = scale
        self._pet_w = max(1, round(self._cw * scale))
        self._pet_h = max(1, round(self._ch * scale))
        self._side = 26
        self._top_space = 124
        self._paint_w = self._pet_w + self._side * 2
        self._paint_h = self._pet_h + self._top_space + 5
        self.setFixedSize(self._paint_w, self._paint_h)
        self._x = feet_x - self._pet_w / 2 - self._side
        self._snap_x()
        if self._mode not in {
            Activity.DRAG.value,
            Activity.FALL.value,
            Activity.CLIMB.value,
        }:
            self._y = self._ground_window_y()
        self.move(round(self._x), round(self._y))
        self.update()

    # ------------------------------------------------------------------
    # modes
    # ------------------------------------------------------------------
    def _set_mode(self, mode: str, *, keep_position: bool = True) -> None:
        if mode == self._mode:
            return
        now = time.monotonic()
        old = self._mode
        self._mode = mode
        self._mode_started = now
        self.model.set_activity(mode)
        # 30 Hz is plenty: the held pose is a slow damped lean plus a ≤1.5 Hz
        # float, not an 8 Hz pulse that would alias at this tick rate.
        ticker = getattr(self, "_ticker", None)
        if ticker is not None:
            # The hop uses per-frame interpolation, so walk gets the 60 FPS
            # grid while every other state stays at the efficient 30 FPS tick.
            ticker.setInterval(16 if mode == Activity.WALK.value else 33)
        if mode == Activity.IDLE.value:
            self._direction = self._rng.choice((-1, 1))
            self._facing = self._direction
            self._next_decision = now + self._autonomy.next_delay()
            self._sit_until = 0.0
            self._reset_hop()
        elif mode == Activity.WALK.value:
            # A roam segment is only 2–3 leisurely hops (30–45 px at 15 px per
            # hop), then the pet goes back to an idle breathing pause.
            roam_steps = self._rng.randint(2, 3)
            self._walk_until = now + self._hop.total_time * roam_steps
            self._walk_speed = ROAM_SPEED
            self._sit_until = 0.0
            self._begin_hop(now)
        elif mode == Activity.SIT.value:
            self._sit_until = now + self._rng.uniform(10.0, 20.0)
            self._walk_speed = 0.0
            self._snap_x()
            self._set_grounded()
        elif mode == Activity.DRAG.value:
            self._start_sweat()
        elif mode == Activity.FALL.value:
            self._fall_bounces = 0
        elif mode == Activity.SLEEP.value:
            self._sleep_started = now
            self._next_zzz = now + 0.35
            self._snap_x()
            self._set_grounded()
        elif mode == Activity.EAT.value:
            self._eat_started = now
        elif mode == Activity.STUDY.value:
            self._study_end = now + 30.0
        elif mode == Activity.RAGE.value:
            self._rage_started = now
        if mode != Activity.IDLE.value:
            self._idle_tilt_until = 0.0
            self._idle_tilt_angle = 0.0
        if mode not in {
            Activity.DRAG.value,
            Activity.FALL.value,
            Activity.CLIMB.value,
        }:
            self._fade_sweat()
        if mode != Activity.WALK.value:
            self._reset_hop()
        if old == Activity.SLEEP.value and mode != Activity.SLEEP.value:
            self.model.wake()
        self._notify_stats()
        self.update()

    def _start_walk(self, direction: int | None = None, duration: float | None = None) -> None:
        if self._bust_mode:
            return
        self._direction = direction if direction in (-1, 1) else self._rng.choice((-1, 1))
        now = time.monotonic()
        self._set_mode(Activity.WALK.value)
        if duration is not None:
            self._walk_until = now + max(1.0, float(duration))

    def _start_sit(self, duration: float | None = None) -> None:
        now = time.monotonic()
        self._set_mode(Activity.SIT.value)
        if duration is not None:
            self._sit_until = now + max(5.0, float(duration))

    def _reset_hop(self) -> None:
        self._hop_y = 0.0
        self._hop_scale_x = 1.0
        self._hop_scale_y = 1.0
        self._hop_distance = 0.0
        self._resting_sit = False
        self._hop_cycle_started = time.monotonic()

    def _begin_hop(self, now: float) -> None:
        """Start one charge → airborne → land cycle, clamped to screen edges."""

        self._hop_start_x = self._x
        self._hop_cycle_started = now
        self._hop_y = 0.0
        self._hop_scale_x = 1.0
        self._hop_scale_y = 1.0
        self._resting_sit = False
        rect = self._current_screen_rect()
        left_edge, right_edge = self._body_edges()
        if self._direction >= 0:
            available = rect.right() - right_edge
        else:
            available = left_edge - rect.left()
        if available < 4.0:
            # Turn at the edge before spending a whole hop on a blocked step.
            self._direction *= -1
            self._facing = 1 if self._direction > 0 else -1
            if self._direction > 0:
                available = rect.right() - right_edge
            else:
                available = left_edge - rect.left()
        self._facing = 1 if self._direction > 0 else -1
        distance = min(self._hop.distance, max(0.0, available))
        self._hop_distance = distance if self._direction > 0 else -distance

    def _hop_step(self, now: float, dt: float) -> None:
        sample: HopSample = self._hop.sample(now - self._hop_cycle_started)
        self._resting_sit = sample.phase == "rest"
        ratio = (
            sample.x_offset / self._hop.distance
            if self._hop.distance > 0.0
            else 0.0
        )
        self._x = self._hop_start_x + self._hop_distance * ratio
        self._hop_y = sample.y_offset
        self._hop_scale_x = sample.scale_x
        self._hop_scale_y = sample.scale_y
        rect = self._current_screen_rect()
        left_edge, right_edge = self._body_edges()
        if left_edge < rect.left():
            self._x += rect.left() - left_edge
        elif right_edge > rect.right():
            self._x -= right_edge - rect.right()
        self._y = self._ground_window_y()
        self.move(round(self._x), round(self._y))
        if sample.completed:
            self._x = self._hop_start_x + self._hop_distance
            self.move(round(self._x), round(self._y))
            if now >= self._walk_until:
                self._set_mode(Activity.IDLE.value)
                # After a short roam, stand and breathe for 5–10 s before the
                # next autonomous decision, instead of immediately hopping on.
                self._next_decision = now + self._rng.uniform(5.0, 10.0)
            else:
                self._begin_hop(now)
        self.update()

    def _apply_idle_doodle(self, decision: WanderDecision) -> None:
        """Stand still and perform one tiny readable action."""

        now = time.monotonic()
        if self._mode != Activity.IDLE.value:
            self._set_mode(Activity.IDLE.value)
        self._next_decision = now + max(1.0, decision.duration)
        if decision.doodle == "blink":
            self._blink_until = now + self.config.motion.blink_duration
            self._next_blink = now + self._rng.uniform(
                self.config.motion.blink_interval_min,
                self.config.motion.blink_interval_max,
            )
        elif decision.doodle == "tilt":
            self._idle_tilt_angle = self._rng.choice((-8.0, -6.0, 6.0, 8.0))
            self._idle_tilt_until = now + self._rng.uniform(1.3, 2.1)
        elif decision.doodle == "sigh":
            self.say(
                self._rng.choice(["唉……", "今天也一般般。", "发会儿呆。", "桌面真安静。"]),
                priority=0,
                duration=2.8,
            )
        else:
            self._spawn_sparkles(1)
            self.model.pulse(Expression.HAPPY.value, 1.0)

    def _perform_idle_decision(self, now: float) -> None:
        if self._mode != Activity.IDLE.value:
            return
        if not self._at_floor(4.0):
            self._next_decision = now + self._autonomy.next_delay()
            return
        # Don't juggle too many behaviours while a bubble is being read.
        if self._bubble and now < self._bubble.expires - 1.0:
            self._next_decision = now + 1.2
            return
        decision = self._autonomy.decide(now, can_walk=not self._bust_mode)
        if decision.is_walk:
            # A roam is deliberately short: 2–3 hops, then idle breathing.
            self._start_walk(decision.direction)
        elif decision.is_sit:
            self._start_sit(decision.duration)
        else:
            self._apply_idle_doodle(decision)

    def _interrupt_autonomy(self) -> None:
        """User input always wins over wandering / resting / doodling."""

        now = time.monotonic()
        self._idle_tilt_until = 0.0
        self._idle_tilt_angle = 0.0
        if self._mode in {
            Activity.WALK.value,
            Activity.SIT.value,
            Activity.CLIMB.value,
        }:
            self._set_mode(Activity.IDLE.value)
        # Push the next autonomous choice 8–15 s out after every interaction.
        self._next_decision = now + self._autonomy.next_delay()

    def _start_climb(self, side: int) -> None:
        if self._bust_mode or not self._at_floor(5.0):
            return
        rect = self._current_screen_rect()
        self._climb_side = side
        if side > 0:
            # right wall
            self._x = rect.right() - self._side - self._pet_w * 0.925
        else:
            self._x = rect.left() - self._side - self._pet_w * 0.075
        self._climb_started = time.monotonic()
        self._climb_until = self._climb_started + 2.0
        self._set_mode(Activity.CLIMB.value)
        self.say(
            self._rng.choice(["看我飞檐走壁！", "这墙，我爬定了。", "别拦我，我要上墙。"]),
            priority=0,
            duration=2.0,
        )
        self._next_climb_allowed = time.monotonic() + 18.0

    # ------------------------------------------------------------------
    # public actions used by menus / tray
    # ------------------------------------------------------------------
    def _maybe_auto_godot(self) -> None:
        """Use Godot automatically when a local executable is available.

        ``DESKLING_RENDERER=pyqt`` forces the native renderer.  If Godot exits
        later, :meth:`_sync_godot_renderer` drops the bridge and QPainter
        paints the pet again, so startup never depends on Godot.
        """

        if os.environ.get("DESKLING_RENDERER", "").strip().lower() in {
            "pyqt",
            "2d",
            "0",
            "off",
        }:
            return
        self.enable_godot_renderer()

    def enable_godot_renderer(self) -> bool:
        """Optionally launch the Godot 4 render shell for this character.

        The normal PyQt pet remains the input/tray owner; this bridge is for
        machines that have a local Godot 4 executable and want the transparent
        Godot preview.  It returns ``False`` cleanly when Godot is absent.
        """

        if self._godot_bridge is not None:
            return True
        try:
            from .godot_bridge import GodotBridge
        except Exception:
            return False
        bridge = GodotBridge(self.config.folder)
        if not bridge.available:
            return False
        if not bridge.start(
            width=self.width(),
            height=self.height(),
            x=self.x(),
            y=self.y(),
            scale=self._scale,
            offset_x=self._side,
            offset_y=self._top_space,
        ):
            return False
        self._godot_bridge = bridge
        self._sync_godot_renderer()
        self.update()
        return True

    @property
    def _godot_active(self) -> bool:
        return self._godot_bridge is not None and self._godot_bridge.running

    def _sync_godot_renderer(self) -> None:
        if self._godot_bridge is None:
            return
        if not self._godot_bridge.running:
            try:
                self._godot_bridge.stop()
            except Exception:
                pass
            self._godot_bridge = None
            self.update()
            return
        try:
            self._godot_bridge.update(
                x=self.x(),
                y=self.y(),
                width=self.width(),
                height=self.height(),
                scale=self._scale,
                offset_x=self._side,
                offset_y=self._top_space,
                state=self._mode,
                pose=self._current_pose(),
                vx=self._pointer_vx,
            )
        except Exception:
            log.debug("Godot renderer state update failed", exc_info=True)

    def activate(self) -> None:
        self.raise_()
        self.activated.emit(self)

    def greet(self, include_hint: bool = False) -> None:
        if self._greeted:
            return
        self._greeted = True
        self._hint_enabled = include_hint
        self.say(
            self.config.pick_line("greet"),
            priority=1,
            voice_kind="happy",
            duration=4.2,
        )
        if include_hint:
            self._hint_due = time.monotonic() + 5.6

    def pat(self, *, force: bool = False, quiet: bool = False) -> None:
        now = time.monotonic()
        if not force and now < self._pat_cooldown:
            return
        if self._mode == Activity.RAGE.value:
            return
        self._interrupt_autonomy()
        self._pat_cooldown = now + 0.22
        self._pat_count += 1
        self.model.pat()
        if self._mode == Activity.SLEEP.value:
            self._spawn_zzz(1)
            if not quiet and self._pat_count % 6 == 0:
                self.say(self.config.pick_line("sleep"), priority=0, duration=2.6)
            self.update()
            return
        self._spawn_hearts(3 if self._pat_count % 4 else 5)
        self._play_sfx("pat")
        if force or self._bubble is None or self._pat_count % 3 == 1:
            self.say(self.config.pick_line("pat"), priority=1, voice_kind="happy")
        self._notify_stats()
        self.update()

    def poke(self) -> None:
        if self._mode == Activity.RAGE.value:
            return
        if self._mode == Activity.SLEEP.value:
            self.wake_up(by_user=True)
            return
        self._interacted = True
        self._interrupt_autonomy()
        now = time.monotonic()
        combo = self._register_click(now)
        anger_before = self.model.anger
        ready = self.model.poke()
        if not combo:
            self._play_sfx("pop")
            self._play_voice("poke")
        self._spawn_sparkles(2)
        # Crossing an anger band gets its own comment; otherwise the usual
        # "stop poking me" line.  A 3-hit combo uses the rage line instead.
        line = self._note_anger_rise(anger_before)
        if not combo:
            self.say(line or self.config.pick_line("poke"), priority=2, voice=False)
        if ready:
            self._rage_pending_at = time.monotonic() + 0.55
        self._notify_stats()
        self.update()

    def _register_click(self, now: float | None = None) -> bool:
        """Bounce the sprite and return True when this click made a combo."""

        now = time.monotonic() if now is None else now
        # 0.8 × the configured 5% envelope = a 4% vertical jelly squash.
        self._tap_bounce.trigger(now, strength=0.8)
        if self._click_combo.tap(now):
            self._trigger_combo(now)
            return True
        return False

    def _trigger_combo(self, now: float) -> None:
        """Rapid-click reaction: jumping 💢, red-hot face and a rage line."""

        self._combo_mark_born = now
        self._combo_mark_until = now + self.config.motion.combo_mark_seconds
        self._combo_angry_until = now + self.config.motion.combo_angry_seconds
        self.model.pulse(Expression.ANGRY.value, self.config.motion.combo_angry_seconds)
        self._rig.kick(0.9)
        self._play_sfx("rage")
        self.say(
            self.config.pick_line("rage"),
            priority=3,
            duration=2.6,
            voice_kind="angry",
        )
        self.update()

    def _note_anger_rise(self, before: float) -> str:
        """Return a bubble line when the anger just crossed into a new band."""

        after = self.model.anger
        band = int(min(100.0, after) // (100.0 / ANGER_BANDS))
        if after <= before + 0.4 or band <= self._anger_band:
            return ""
        self._anger_band = band
        return self.config.pick_line("anger")

    def feed_item(self, food: FoodItem) -> None:
        if self._mode == Activity.RAGE.value:
            self.say("正在气头上，不吃！", priority=2)
            return
        if self._mode == Activity.SLEEP.value:
            self.wake_up(by_user=False, silent=True)
        self._interrupt_autonomy()
        self._cancel_study()
        anger_before = self.model.anger
        outcome = self.model.feed(food)
        # Keep the original PNG; the socket layer owns scaling/placement.
        self._food_pixmap = self.common.pixmap(food.file)
        self._food_item = food
        self._food_start_eat()
        if food.anger > 0:
            self._tap_bounce.trigger(time.monotonic(), strength=0.85)
            line = self._note_anger_rise(anger_before) or "嘶——辣辣辣！这是化学武器吧！"
            self.say(line, priority=2, voice_kind="angry")
        else:
            self.say(self.config.pick_line("feed"), priority=1, voice_kind="happy")
        self._play_sfx("eat")
        self._notify_stats()
        _ = outcome

    def feed_external(self, path: Path) -> None:
        try:
            info = path.stat()
        except OSError as exc:
            self.say(f"打不开这个文件（{exc.__class__.__name__}）。", priority=2)
            return
        if self._mode == Activity.RAGE.value:
            self.say("气都气饱了，拿开！", priority=2)
            return
        if self._mode == Activity.SLEEP.value:
            self.wake_up(by_user=False, silent=True)
        self._interrupt_autonomy()
        name = path.name or str(path)
        short_name = name if len(name) <= 22 else name[:19] + "…"
        if path.is_dir():
            self._tap_bounce.trigger(time.monotonic(), strength=0.6)
            self.say("文件夹太大了，一口吞不下。", priority=2)
            return
        if info.st_size > 8 * 1024 * 1024:
            self.say(self.config.pick_line("too_big"), priority=2)
            return
        suffix = path.suffix.lower()
        if suffix in {".exe", ".dll", ".msi", ".sys", ".bin", ".iso"} or name.startswith("."):
            reject_chance = 0.8
        else:
            reject_chance = 0.28
        if self.model.hunger > 72:
            reject_chance -= 0.12
        accepted = self._rng.random() > reject_chance
        if not accepted:
            self.model.reject_food()
            self._tap_bounce.trigger(time.monotonic(), strength=0.8)
            self._spawn_crumbs(6, dirty=True)
            self.say(f"呸！「{short_name}」这东西能吃吗？", priority=2, voice_kind="angry")
            self._play_sfx("pop")
            self._notify_stats()
            self.update()
            return

        self._cancel_study()
        self.model.eat_external()
        icon = QFileIconProvider().icon(QFileInfo(str(path)))
        pm = icon.pixmap(QSize(160, 160))
        if pm.isNull() and self.catalog.foods:
            pm = self.common.pixmap(next(iter(self.catalog.foods.values())).file)
        self._food_pixmap = pm
        self._food_item = None
        self._food_start_eat()
        self._play_sfx("eat")
        line = self.config.pick_line("file_eat")
        self.say(f"「{short_name}」……{line}", priority=1, voice_kind="happy")
        self._notify_stats()
        self.update()

    def _food_start_eat(self) -> None:
        self._eat_started = time.monotonic()
        self._eat_end = self._eat_started + 2.25
        self._crumbing_done = False
        self._snap_x()
        self._set_grounded()
        self._set_mode(Activity.EAT.value)

    def sleep_now(self, *, auto: bool = False) -> None:
        if self._mode == Activity.SLEEP.value:
            return
        if self._mode in {Activity.DRAG.value, Activity.FALL.value}:
            return
        self._interrupt_autonomy()
        self._cancel_study()
        self._snap_x()
        self._set_grounded()
        self._set_mode(Activity.SLEEP.value)
        if not auto:
            self.say(self.config.pick_line("sleep"), priority=1, voice_kind="sleep")
        else:
            self.say(self.config.pick_line("sleep"), priority=0)
        self._play_sfx("sparkle")
        self._notify_stats()

    def wake_up(self, *, by_user: bool = False, silent: bool = False) -> None:
        if self._mode != Activity.SLEEP.value:
            return
        self.model.wake()
        self._set_mode(Activity.IDLE.value)
        self._spawn_sparkles(3)
        if not silent:
            self.say(self.config.pick_line("wake"), priority=2 if by_user else 1, voice_kind="happy")
        self._notify_stats()

    def study_now(self) -> None:
        if self._mode == Activity.RAGE.value:
            return
        if self._mode == Activity.SLEEP.value:
            self.wake_up()
        if self._mode == Activity.EAT.value:
            return
        self._interrupt_autonomy()
        self._snap_x()
        self._set_grounded()
        self._set_mode(Activity.STUDY.value)
        self.say(self.config.pick_line("study"), priority=1)
        self._spawn_sparkles(2)
        self._play_sfx("sparkle")

    def stop_studying(self) -> None:
        if self._mode != Activity.STUDY.value:
            return
        self._set_mode(Activity.IDLE.value)
        self.say(self.config.pick_line("study_end"), priority=1)
        self._spawn_sparkles(2)

    def _cancel_study(self) -> None:
        if self._mode == Activity.STUDY.value:
            self._set_mode(Activity.IDLE.value)

    def toggle_wardrobe(self, item: WardrobeItem) -> None:
        """Toggle one small accessory (head_top / face / hand).

        There is intentionally no torso/outfit branch: a full-body garment PNG
        cannot follow arbitrary silhouettes and used to show up as a misplaced
        rectangle.  Only anchor-mounted accessories are supported.
        """

        if not self.config.has_costumes or not item.is_accessory:
            # Custom single-image characters have no costume pack; catalogue
            # wigs/shades must never be glued onto them.
            return
        self._interrupt_autonomy()
        access = set(self._accessories)
        if item.id in access:
            access.remove(item.id)
        else:
            access.add(item.id)
        self._accessories = self._normalise_accessories(access)
        self._set_grounded()
        self._spawn_sparkles(4)
        self._play_sfx("sparkle")
        self.say(
            self._rng.choice(["怎么样？好看吗？", "这个小挂件可以吧，不许笑。", "换装完成，原地出道。"]),
            priority=1,
        )
        self.update()

    def clear_wardrobe(self) -> None:
        self._accessories = ()
        self._spawn_sparkles(3)
        self.say("还是原来的自己最舒服。", priority=1)
        self.update()

    def _normalise_accessories(self, ids: Iterable[str]) -> tuple[str, ...]:
        """Keep one accessory per supported socket; drop legacy/outfit IDs."""

        if not self.config.has_costumes:
            return ()
        by_mount: dict[str, str] = {}
        for item_id in ids:
            item = self.catalog.item(item_id)
            if item is None or not item.is_accessory:
                continue
            by_mount[item.mount] = item.id
        return tuple(sorted(by_mount.values()))

    def force_rage(self, manual: bool = True) -> bool:
        if self._mode == Activity.SLEEP.value:
            self.wake_up(silent=True)
        self._interrupt_autonomy()
        if self._mode == Activity.RAGE.value:
            return False
        if self.model.rage_cooldown > 0:
            if manual:
                self.say("我还在消气，等会儿再惹我。", priority=1)
            return False
        return self._begin_rage_visuals()

    def react_to_activity(self, category: str) -> None:
        if self._mode in {
            Activity.SLEEP.value,
            Activity.DRAG.value,
            Activity.FALL.value,
            Activity.RAGE.value,
        }:
            return
        if category == "work":
            self.model.pulse(Expression.HAPPY.value, 2.2)
            line = self.config.pick_line("work")
            self.say(line, priority=0, voice_kind="happy")
            self._spawn_sparkles(2)
        elif category == "play":
            self.model.pulse(Expression.SMUG.value, 2.4)
            line = self.config.pick_line("play")
            self.say(line, priority=0, duration=4.2)
        self.update()

    def tidy_for_capture(self) -> None:
        """Small helper for screenshot tooling and manual smoke tests."""

        self._set_grounded()
        self._snap_x()
        self.move(round(self._x), round(self._y))
        self.update()

    # ------------------------------------------------------------------
    # speech / particles / audio
    # ------------------------------------------------------------------
    def say(
        self,
        text: str,
        *,
        priority: int = 1,
        duration: float | None = None,
        voice_kind: str = "",
        voice: bool = False,
    ) -> None:
        """Pop a comic bubble above the head.

        ``duration`` is how long the bubble stays fully readable; after that it
        fades out over :data:`BUBBLE_FADE` seconds.  Interaction bubbles use
        :data:`BUBBLE_HOLD` by default.
        """

        text = str(text).strip()
        if not text:
            return
        now = time.monotonic()
        if self._bubble and self._bubble.priority > priority and now < self._bubble.expires:
            return
        if duration is None:
            duration = BUBBLE_HOLD
        duration = max(0.6, float(duration))
        self._bubble = Bubble(
            text=text,
            born=now,
            hold_until=now + duration,
            expires=now + duration + BUBBLE_FADE,
            priority=priority,
            voice=voice_kind,
        )
        self._last_bubble_line = text
        if voice_kind:
            self._play_voice(voice_kind)
        self.update()

    def _play_voice(self, kind: str) -> None:
        if self.audio is not None and self.settings.sound_enabled:
            try:
                self.audio.voice(self.config, kind)
            except Exception:
                log.debug("voice playback failed", exc_info=True)

    def _play_sfx(self, name: str) -> None:
        if self.audio is not None and self.settings.sound_enabled:
            try:
                self.audio.sfx(name)
            except Exception:
                log.debug("sfx playback failed", exc_info=True)

    def _spawn_hearts(self, count: int) -> None:
        hx, hy, hw, hh = self.config.head_rect
        cx = self._side + (hx + hw / 2) * self._pet_w
        cy = self._top_space + (hy + hh * 0.28) * self._pet_h
        for _ in range(count):
            self._add_particle(
                Particle(
                    kind="heart",
                    x=cx + self._rng.uniform(-self._pet_w * 0.22, self._pet_w * 0.22),
                    y=cy + self._rng.uniform(-10, 12),
                    vx=self._rng.uniform(-24, 24),
                    vy=self._rng.uniform(-72, -38),
                    life=self._rng.uniform(0.8, 1.3),
                    max_life=1.3,
                    size=self._rng.uniform(10, 17),
                    colour=QColor(self._rng.choice(("#F27793", "#F49BAA", "#E75C78", "#FFB1BB"))),
                )
            )

    def _spawn_sparkles(self, count: int) -> None:
        hx, hy, hw, hh = self.config.head_rect
        cx = self._side + (hx + hw / 2) * self._pet_w
        cy = self._top_space + (hy + hh * 0.35) * self._pet_h
        for _ in range(count):
            self._add_particle(
                Particle(
                    kind="sparkle",
                    x=cx + self._rng.uniform(-self._pet_w * 0.34, self._pet_w * 0.34),
                    y=cy + self._rng.uniform(-self._pet_h * 0.18, self._pet_h * 0.18),
                    vx=self._rng.uniform(-15, 15),
                    vy=self._rng.uniform(-35, -12),
                    life=self._rng.uniform(0.55, 0.95),
                    max_life=0.95,
                    size=self._rng.uniform(5, 10),
                    colour=QColor(self._rng.choice(("#FFD166", "#FFEBB0", "#FFF7DE"))),
                )
            )

    def _spawn_crumbs(self, count: int, dirty: bool = False) -> None:
        mx = self._side + self.config.mouth[0] * self._pet_w
        my = self._top_space + self.config.mouth[1] * self._pet_h
        colors = ("#D39A55", "#A56A3A", "#E4B57D") if not dirty else ("#6F8B4D", "#9EAD65", "#4B5D35")
        for _ in range(count):
            self._add_particle(
                Particle(
                    kind="crumb",
                    x=mx + self._rng.uniform(-10, 10),
                    y=my + self._rng.uniform(-4, 8),
                    vx=self._rng.uniform(-60, 60),
                    vy=self._rng.uniform(-90, -20),
                    life=self._rng.uniform(0.35, 0.7),
                    max_life=0.7,
                    size=self._rng.uniform(2.5, 5.0),
                    colour=QColor(self._rng.choice(colors)),
                    gravity=420.0,
                )
            )

    def _spawn_dust(self) -> None:
        cx = self._side + self._pet_w / 2
        cy = self._top_space + self._pet_h - 5
        for _ in range(7):
            self._add_particle(
                Particle(
                    kind="dust",
                    x=cx + self._rng.uniform(-self._pet_w * 0.3, self._pet_w * 0.3),
                    y=cy + self._rng.uniform(-3, 3),
                    vx=self._rng.uniform(-42, 42),
                    vy=self._rng.uniform(-36, -8),
                    life=self._rng.uniform(0.3, 0.55),
                    max_life=0.55,
                    size=self._rng.uniform(5, 12),
                    colour=QColor(121, 103, 92, 95),
                )
            )

    def _spawn_zzz(self, count: int = 1) -> None:
        """Float the sleeping 💤 puffs just above the hat."""

        hx, hy, hw, hh = self.config.head_rect
        cx = self._side + (hx + hw * 0.88) * self._pet_w
        cy = self._top_space + (hy - 0.015) * self._pet_h
        base_size = max(14.0, self._pet_w * 0.10)
        for i in range(count):
            size = base_size * self._rng.uniform(0.86, 1.12)
            self._add_particle(
                Particle(
                    kind="zzz",
                    x=cx + i * size * 0.5,
                    y=cy - i * size * 0.35,
                    vx=self._rng.uniform(4, 11),
                    vy=self._rng.uniform(-18, -11),
                    life=self._rng.uniform(1.7, 2.5),
                    max_life=2.5,
                    size=size,
                    colour=QColor(126, 150, 205),
                    text="💤",
                    phase=self._rng.uniform(0.0, math.tau),
                )
            )

    def _add_particle(self, particle: Particle) -> None:
        self._particles.append(particle)
        if len(self._particles) > MAX_PARTICLES:
            del self._particles[: len(self._particles) - MAX_PARTICLES]

    def _start_sweat(self) -> None:
        """Show the ambient held sweat drop without touching the face."""

        self._sweat_visible = True
        self._sweat_target = 1.0

    def _fade_sweat(self) -> None:
        self._sweat_target = 0.0

    def _update_sweat(self, now: float, dt: float) -> None:
        if not self._sweat_visible:
            return
        follow = min(1.0, dt * (7.0 if self._sweat_target > self._sweat_alpha else 3.0))
        self._sweat_alpha += (self._sweat_target - self._sweat_alpha) * follow
        if self._sweat_target <= 0.0 and self._sweat_alpha < 0.01:
            self._sweat_alpha = 0.0
            self._sweat_visible = False

    # ------------------------------------------------------------------
    # update loop
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        if not self.isVisible():
            return
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        if dt <= 0:
            return
        dt = min(dt, 0.08)

        self.model.tick(dt)
        self._sync_anger_band()
        self._update_blink(now)
        self._update_bubble(now)
        self._update_behavior(now, dt)
        self._update_rig(now, dt)
        self._update_head_inertia(dt)
        self._update_particles(dt)
        self._update_sweat(now, dt)
        self._update_auto_life(now)
        self._sync_godot_renderer()

        if self._rage_pending_at is not None and now >= self._rage_pending_at:
            self._rage_pending_at = None
            self._begin_rage_visuals()
        if self._rage_emit_at is not None and now >= self._rage_emit_at:
            self._rage_emit_at = None
            self.rage_requested.emit(self, self._rage_emit_line)

        if self._greet_due is not None and now >= self._greet_due and self._mode not in {
            Activity.FALL.value,
            Activity.DRAG.value,
        }:
            self._greet_due = None
            if not self._greeted and not self._interacted:
                self.greet(self._hint_enabled)
        if self._hint_due is not None and now >= self._hint_due:
            self._hint_due = None
            if not self._bubble:
                self.say(
                    self.config.pick_line("welcome_hint"),
                    priority=0,
                    duration=5.5,
                )
        self.update()

    def _update_blink(self, now: float) -> None:
        motion = self.config.motion
        if now >= self._next_blink:
            if self.model.awake() and self.model.face(False) == Expression.NORMAL.value:
                self._blink_until = now + motion.blink_duration
            self._next_blink = now + self._rng.uniform(
                motion.blink_interval_min, motion.blink_interval_max
            )

    def _update_rig(self, now: float, dt: float) -> None:
        """Feed the current movement into the joint springs."""

        if self._mode == Activity.DRAG.value:
            if now - self._last_pointer_time > 0.07:
                decay = max(0.0, 1.0 - dt * 12.0)
                self._pointer_vx *= decay
                self._pointer_vy *= decay
            vx, vy = self._pointer_vx, self._pointer_vy
        else:
            vx, vy = self._vx, self._vy
        gait = (now - self._mode_started) * 7.2
        sleeping = self._mode == Activity.SLEEP.value
        self._rig_pose = self._rig.update(
            dt,
            vx=vx,
            vy=vy,
            mode="sleep" if sleeping else self._mode,
            now=now,
            walk_gait=gait,
            direction=self._direction,
            climb_side=self._climb_side,
            sleeping=sleeping,
        )

    def _update_head_inertia(self, dt: float) -> None:
        """Damped head lag, never more than ±6° from the body axis."""

        if self._mode == Activity.DRAG.value:
            target = -self._pointer_vx * 0.010
        elif self._mode == Activity.WALK.value:
            target = self._direction * 2.2
        elif self._mode == Activity.FALL.value:
            target = -self._vx * 0.006
        else:
            target = 0.0
        target = max(-6.0, min(6.0, target))
        # A light spring keeps the head one beat behind the torso, then lets
        # it settle without oscillation or a snap.
        accel = (target - self._head_inertia) * 70.0 - self._head_inertia_v * 11.0
        self._head_inertia_v += accel * dt
        self._head_inertia += self._head_inertia_v * dt
        if abs(self._head_inertia) > 6.0:
            self._head_inertia = max(-6.0, min(6.0, self._head_inertia))
            if (self._head_inertia > 0 and self._head_inertia_v > 0) or (
                self._head_inertia < 0 and self._head_inertia_v < 0
            ):
                self._head_inertia_v = 0.0

    def _sync_anger_band(self) -> None:
        band = int(self.model.anger // (100.0 / ANGER_BANDS))
        if band < self._anger_band:
            self._anger_band = band

    def _update_bubble(self, now: float) -> None:
        if self._bubble and now >= self._bubble.expires:
            self._bubble = None

    def _update_behavior(self, now: float, dt: float) -> None:
        mode = self._mode
        if mode in {
            Activity.IDLE.value,
            Activity.WALK.value,
            Activity.SIT.value,
            Activity.EAT.value,
            Activity.STUDY.value,
            Activity.RAGE.value,
            Activity.SLEEP.value,
        }:
            if not self._at_floor(3.0):
                self._set_grounded()
            else:
                self._y = self._ground_window_y()
        if mode == Activity.IDLE.value:
            if now >= self._next_decision:
                self._perform_idle_decision(now)
        elif mode == Activity.WALK.value:
            if self._bust_mode:
                self._set_mode(Activity.IDLE.value)
            else:
                self._hop_step(now, dt)
        elif mode == Activity.SIT.value:
            if now >= self._sit_until:
                self._set_mode(Activity.IDLE.value)
                self._next_decision = now + self._autonomy.next_delay()
        elif mode == Activity.FALL.value:
            self._fall_step(now, dt)
        elif mode == Activity.CLIMB.value:
            if self._bust_mode:
                self._set_grounded()
                self._set_mode(Activity.IDLE.value)
            else:
                self._climb_step(now, dt)
        elif mode == Activity.EAT.value:
            if now >= self._eat_end:
                self._food_pixmap = None
                self._food_item = None
                self._set_mode(Activity.IDLE.value)
                self._next_decision = now + self._autonomy.next_delay()
                self._crumbing_done = False
                if self._rng.random() < 0.55:
                    self._spawn_hearts(2)
        elif mode == Activity.STUDY.value:
            if now >= self._study_end:
                self._set_mode(Activity.IDLE.value)
                self.say(self.config.pick_line("study_end"), priority=1)
                self._spawn_sparkles(2)
        elif mode == Activity.SLEEP.value:
            if now >= self._next_zzz:
                self._spawn_zzz(1)
                self._next_zzz = now + self._rng.uniform(0.75, 1.25)
            if self.model.energy >= 99.4 and now - self._sleep_started > 5.0:
                self.wake_up(by_user=False, silent=True)
                self.say(self.config.pick_line("wake"), priority=1, voice_kind="happy")
        elif mode == Activity.RAGE.value:
            if now >= self._rage_end:
                self.model.finish_rage()
                self._set_mode(Activity.IDLE.value)
                self._next_decision = now + self._autonomy.next_delay()
                self._spawn_dust()
                self.update()
        elif mode == Activity.DRAG.value:
            self._direction = 1 if self._vx >= 0 else -1
        # an automatic rage even if the last interaction wasn't a poke
        if (
            self._mode not in {Activity.RAGE.value, Activity.DRAG.value, Activity.FALL.value, Activity.SLEEP.value}
            and self.model.can_rage()
            and self._rage_pending_at is None
        ):
            self._rage_pending_at = now + 0.45

    def _fall_step(self, now: float, dt: float) -> None:
        self._vy += 1750.0 * dt
        self._y += self._vy * dt
        self._x += self._vx * dt
        rect = self._current_screen_rect()
        left_edge, right_edge = self._body_edges()
        if left_edge < rect.left():
            self._x += rect.left() - left_edge
            self._vx = abs(self._vx) * 0.3
        elif right_edge > rect.right():
            self._x -= right_edge - rect.right()
            self._vx = -abs(self._vx) * 0.3
        self._y = max(self._y, rect.top() - 100.0)
        ground = self._ground_window_y()
        if self._y >= ground:
            impact = max(0.0, self._vy)
            self._y = ground
            if impact > 280.0 and self._fall_bounces < 2:
                self._rig.land(impact, bounce=True)
                self._vy = -impact * 0.28
                self._vx *= 0.65
                self._fall_bounces += 1
                self._spawn_dust()
                self._play_sfx("pop")
            else:
                self._rig.land(impact)
                self._vy = 0.0
                self._vx = 0.0
                self._y = ground
                self._spawn_dust()
                was_dropped = self._landed_from_drag
                self._landed_from_drag = False
                self._set_mode(Activity.IDLE.value)
                self._fade_sweat()
                self._next_decision = now + self._autonomy.next_delay()
                if was_dropped and impact > 130:
                    self.say(self.config.pick_line("drop"), priority=1, voice_kind="poke")
                    self._play_sfx("whoosh")
                elif was_dropped:
                    self._play_sfx("pat")
                self._fall_bounces = 0
        self.move(round(self._x), round(self._y))

    def _climb_step(self, now: float, dt: float) -> None:
        rect = self._current_screen_rect()
        self._y -= 52.0 * dt
        head_top = self._y + self._top_space + self.config.head_rect[1] * self._pet_h
        if head_top <= rect.top() + 28 or now >= self._climb_until:
            self._vx = 90.0 * (-self._climb_side)
            self._vy = -60.0
            self._landed_from_drag = False
            self._set_mode(Activity.FALL.value)
            self._spawn_sparkles(2)
        self.move(round(self._x), round(self._y))

    def _update_particles(self, dt: float) -> None:
        alive: list[Particle] = []
        for particle in self._particles:
            particle.life -= dt
            if particle.life <= 0:
                continue
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            particle.vy += particle.gravity * dt
            if particle.kind == "zzz":
                elapsed = particle.max_life - particle.life
                particle.x += math.sin(elapsed * 2.6 + particle.phase) * 9.0 * dt
            if particle.kind in {"heart", "sparkle", "anger", "zzz"}:
                particle.vx *= 0.985
            alive.append(particle)
        self._particles = alive
        self._update_crumbs_during_eat()

    def _update_crumbs_during_eat(self) -> None:
        if self._mode != Activity.EAT.value or self._crumbing_done:
            return
        progress = (time.monotonic() - self._eat_started) / max(0.1, self._eat_end - self._eat_started)
        if progress >= 0.68:
            self._crumbing_done = True
            self._spawn_crumbs(5)

    def _update_auto_life(self, now: float) -> None:
        if self._mode == Activity.SLEEP.value:
            return
        if self.model.energy <= 12 and self._mode in {
            Activity.IDLE.value,
            Activity.WALK.value,
            Activity.SIT.value,
        }:
            self.sleep_now(auto=True)
            return
        if self.model.is_hungry() and now >= self._next_hunger and self._mode not in {
            Activity.DRAG.value,
            Activity.FALL.value,
            Activity.RAGE.value,
            Activity.EAT.value,
        }:
            self.say(self.config.pick_line("hungry"), priority=0, duration=3.8)
            self._next_hunger = now + self._rng.uniform(50, 85)
        if (
            self._mode == Activity.IDLE.value
            and now >= self._next_chatter
            and self._bubble is None
        ):
            self.say(self.config.pick_line("idle"), priority=0, duration=3.6)
            self._next_chatter = now + self._rng.uniform(30, 65)

    def _begin_rage_visuals(self) -> bool:
        if self._mode == Activity.RAGE.value:
            self._rage_pending_at = None
            return False
        if not self.model.force_rage():
            self._rage_pending_at = None
            return False
        self._snap_x()
        self._set_grounded()
        self._set_mode(Activity.RAGE.value)
        self._rage_end = time.monotonic() + 2.9
        self._tap_bounce.trigger(time.monotonic(), strength=0.9)
        self._rig.kick(1.6)
        self._rage_emit_line = self.config.pick_line("rage")
        self.say(self._rage_emit_line, priority=3, duration=3.2, voice_kind="angry")
        self._play_sfx("rage")
        self._rage_emit_at = time.monotonic() + 0.18
        self._notify_stats()
        return True

    def _notify_stats(self) -> None:
        try:
            self.stats_changed.emit(self)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # painting
    # ------------------------------------------------------------------
    def _current_pose(self) -> str:
        if self._mode in {
            Activity.DRAG.value,
            Activity.FALL.value,
            Activity.CLIMB.value,
        }:
            return "drag"
        if self._mode == Activity.WALK.value:
            if self._resting_sit and self.config.has_dedicated_pose("sit"):
                return "sit"
            if (
                self.config.has_dedicated_pose("idle")
                and not self.config.has_dedicated_pose("walk_left")
                and not self.config.has_dedicated_pose("walk_right")
            ):
                return "idle"
            return "walk_left" if self._direction < 0 else "walk_right"
        if self._mode == Activity.SIT.value:
            return "sit"
        return "idle"

    def _current_expression(self) -> str:
        if self.config.face_static:
            # Locked to the untouched head.png: no blink/angry/sleep swap at
            # all.  Emotion is expressed only by the external 💢 accessory.
            return "normal"
        now = time.monotonic()
        available = self.config.expressions
        # While suspended, keep the original clean face.  The held reaction is
        # an ambient sweat drop above the head, never a painted-on expression.
        if self._mode == Activity.DRAG.value:
            if "normal" in available:
                return "normal"
            return next(iter(available), "normal")
        # A rapid-click combo overrides the usual hit/poke face so the doll
        # actually looks angry instead of merely surprised.
        if now < self._combo_angry_until and "angry" in available:
            return "angry"
        blink = now < self._blink_until
        requested = self.model.face(blink=blink)
        if requested in available:
            return requested
        if requested == Expression.BLINK.value and "normal" in available:
            return "normal"
        if "normal" in available:
            return "normal"
        return next(iter(available), "normal")

    def _paint_character(self, painter: QPainter, now: float) -> None:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # Sleeping is the same live head/body sprite: a slow breath plus the
        # floating 💤 puffs.  No bed, blanket or other code-drawn prop is ever
        # composited over the character, so the old broken-quilt look is gone.
        self._paint_live_sprite(painter, now)

    def _sprite_breath(self, now: float) -> tuple[float, float]:
        """Whole-sprite breathing for single-layer characters and sleep."""

        motion = self.config.motion
        if self._mode == Activity.SLEEP.value:
            wave = math.sin(
                (now - self._mode_started) * motion.sleep_breath_speed
            )
            # A slow chest swell; the tiny width counter-change keeps the
            # sprite from looking like a sticker being mechanically scaled.
            return (
                1.0 - motion.sleep_breath_width * wave,
                1.0 + motion.sleep_breath_scale * wave,
            )
        if not self.assets.has_rig and self._mode in {
            Activity.EAT.value,
            Activity.STUDY.value,
            Activity.CLIMB.value,
            Activity.RAGE.value,
        }:
            wave = math.sin(now * motion.breath_speed + self._rig.phase)
            return (
                1.0 - motion.idle_breath_width * wave,
                1.0 + motion.idle_breath_scale * wave,
            )
        # Idle / walk / sit breathing is handled by the whole-anchor bob in
        # _anchor_bob(), so the single-image body is not stretched.
        return 1.0, 1.0

    def _anchor_bob(self, now: float) -> float:
        """Low-frequency whole-anchor float for flat single-image pets."""

        if self._mode not in {
            Activity.IDLE.value,
            Activity.WALK.value,
            Activity.SIT.value,
        }:
            return 0.0
        motion = self.config.motion
        return (
            math.sin(now * math.tau * motion.anchor_bob_hz + self._rig.phase)
            * motion.anchor_bob
        )

    def _rotation_anchor(self) -> tuple[float, float]:
        """Design-space point the whole sprite rotates around."""

        if self._mode == Activity.FALL.value:
            # In the air the doll hangs around its chest rather than nailing
            # its feet to the bottom edge.
            return self._cw * 0.5, self._ch * 0.58
        if self._mode == Activity.DRAG.value:
            # A held paper doll swings from roughly its centre of mass, not
            # from the floor; otherwise the cursor appears to drag the feet.
            return self._cw * 0.5, self._ch * 0.46
        return self._cw * 0.5, self._ch

    def _uses_pose_texture(self, pose_name: str) -> bool:
        """Whether the current pose is drawn from a pose PNG.

        Single-body characters always use pose textures.  A rigged character
        keeps its articulated body for its built-in walk/drag layers, but a
        *new* dedicated texture (``sit.png``, ``walk.png``, ``drag.png`` …)
        replaces the rig for that pose so pose packs still work.
        """

        if not self.assets.has_rig:
            return True
        if not self.config.has_dedicated_pose(pose_name):
            return False
        path = self.config.pose_path(pose_name)
        if path is None:
            return False
        if pose_name == "sit":
            return True
        legacy_role = {
            "idle": "body",
            "walk_left": "walk",
            "walk_right": "walk",
            "drag": "dangle",
        }.get(pose_name)
        if legacy_role is None:
            return True
        legacy = self.config.layer_path(legacy_role)
        return legacy is None or path.resolve() != legacy.resolve()

    def _paint_live_sprite(self, painter: QPainter, now: float) -> None:
        pose = self._rig_pose
        pose_name = self._current_pose()
        use_pose_texture = self._uses_pose_texture(pose_name)
        expression = self._current_expression()
        head = self.assets.compose_head(expression, self._accessories)

        # A pose-texture walk has no limb rig, so give it a small paper-doll
        # sway/bob.  Articulated rig walks already animate their torso/limbs.
        gait_angle = 0.0
        gait_x = 0.0
        gait_y = 0.0
        if self._mode == Activity.WALK.value and use_pose_texture:
            gait = (now - self._mode_started) * 7.2
            gait_angle = math.sin(gait) * 1.6
            gait_x = math.sin(gait) * 1.2
            gait_y = -abs(math.sin(gait)) * 1.0
        body_angle = pose.body_angle + gait_angle

        tap_x, tap_y = self._tap_bounce.scales(now)
        breath_x, breath_y = self._sprite_breath(now)
        scale_x = self._scale * pose.scale_x * tap_x * breath_x * self._hop_scale_x
        scale_y = self._scale * pose.scale_y * tap_y * breath_y * self._hop_scale_y

        feet_x = self._side + self._pet_w / 2
        feet_y = (
            self._top_space
            + self._pet_h
            + (pose.bob + self._anchor_bob(now)) * self._scale
            + self._hop_y
        )

        painter.save()
        # Squash, stretch and the click bounce all scale around the feet, so
        # the character stays grounded and the head does the visible bobbing.
        painter.translate(feet_x, feet_y)
        painter.scale(scale_x, scale_y)
        painter.translate(-self._cw / 2, -self._ch)
        if abs(gait_x) > 0.001 or abs(gait_y) > 0.001:
            painter.translate(gait_x, gait_y)
        anchor_x, anchor_y = self._rotation_anchor()
        if abs(body_angle) > 0.001:
            painter.translate(anchor_x, anchor_y)
            painter.rotate(body_angle)
            painter.translate(-anchor_x, -anchor_y)
        if self._facing < 0:
            # Mirror the whole painting around its vertical centre so a left
            # hop shows the character facing left instead of moonwalking.
            painter.translate(self._cw, 0.0)
            painter.scale(-1.0, 1.0)

        hx, hy = self.config.pivot("head")
        nx = hx * self._cw
        ny = hy * self._ch

        if use_pose_texture:
            body = self.assets.compose_body(pose_name, self._accessories)
            painter.drawPixmap(0, 0, body)
        else:
            self._paint_rig_body(painter, pose)
        if self._mode == Activity.STUDY.value:
            self._paint_book(painter)

        idle_tilt = (
            self._idle_tilt_angle if now < self._idle_tilt_until else 0.0
        )
        head_angle = pose.head_tilt + idle_tilt + self._head_inertia
        painter.save()
        painter.translate(nx, ny + pose.head_bob)
        painter.rotate(head_angle)
        painter.translate(-nx, -ny)
        painter.drawPixmap(0, 0, head)
        painter.restore()

        if self._mode == Activity.EAT.value and self._food_pixmap is not None:
            self._paint_held_food(painter)
        painter.restore()

    def _paint_combo_mark(self, painter: QPainter, now: float) -> None:
        """Paint the jumping 💢 that appears after three rapid clicks."""

        if now >= self._combo_mark_until:
            return
        elapsed = max(0.0, now - self._combo_mark_born)
        life = elapsed / self.config.motion.combo_mark_seconds
        if life >= 1.0:
            return
        hx, hy, hw, hh = self.config.head_rect
        base_x = self._side + (hx + hw * 0.86) * self._pet_w
        base_y = self._top_space + (hy + hh * 0.03) * self._pet_h
        jump = -abs(math.sin(elapsed * 9.5)) * self._pet_h * 0.035 * (1.0 - life)
        x = base_x + math.sin(elapsed * 13.0) * self._pet_w * 0.012
        y = base_y + jump
        size = max(15, int(self._pet_w * 0.13))
        mark_font = emoji_font(size)
        opacity = 1.0 if life < 0.72 else max(0.0, (1.0 - life) / 0.28)
        pop = min(1.0, elapsed / 0.10)
        scale = 0.72 + 0.28 * (1.0 - (1.0 - pop) ** 2)
        scale += 0.04 * math.sin(elapsed * 19.0)
        painter.save()
        painter.setOpacity(opacity)
        painter.translate(x, y)
        painter.rotate(math.sin(elapsed * 11.0) * 9.0)
        painter.scale(scale, scale)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 92, 102, 46))
        halo = size * 0.62
        painter.drawEllipse(QPointF(0, 0), halo, halo)
        painter.setFont(mark_font)
        painter.setPen(QColor(70, 26, 36))
        painter.drawText(
            QRectF(-size * 0.95, -size * 0.62, size * 1.9, size * 1.3),
            Qt.AlignmentFlag.AlignCenter,
            "💢",
        )
        painter.restore()

    def _paint_rage_mark(self, painter: QPainter, now: float) -> None:
        """Single external 💢 above the head while the rage state is active."""

        if self._mode != Activity.RAGE.value:
            return
        hx, hy, hw, _hh = self.config.head_rect
        size = max(18, int(self._pet_w * 0.16))
        x = self._side + (hx + hw / 2.0) * self._pet_w
        y = self._top_space + (hy - 0.025) * self._pet_h
        bob = math.sin((now - self._rage_started) * 7.0) * 3.0
        painter.save()
        painter.setFont(emoji_font(size))
        painter.setPen(QColor(120, 28, 38))
        painter.drawText(
            QRectF(x - size, y - size + bob, size * 2, size * 2),
            Qt.AlignmentFlag.AlignCenter,
            "💢",
        )
        painter.restore()

    def _draw_pivoted(
        self,
        painter: QPainter,
        pixmap: QPixmap,
        pivot_name: str,
        angle: float,
        scale_y: float = 1.0,
    ) -> None:
        """Draw one limb/torso layer rotated around its joint."""

        if pixmap.isNull():
            return
        px, py = self.config.pivot(pivot_name)
        px *= self._cw
        py *= self._ch
        painter.save()
        painter.translate(px, py)
        painter.rotate(angle)
        if abs(scale_y - 1.0) > 0.0005:
            painter.scale(1.0, scale_y)
        painter.translate(-px, -py)
        painter.drawPixmap(0, 0, pixmap)
        painter.restore()

    def _paint_rig_body(self, painter: QPainter, pose: RigPose) -> None:
        """Paint the five articulated layers with their joint angles."""

        breath = 1.0 + pose.breath * 0.012
        self._draw_pivoted(painter, self.assets.part_pixmap("leg_left"), "leg_left", pose.leg_left)
        self._draw_pivoted(painter, self.assets.part_pixmap("leg_right"), "leg_right", pose.leg_right)
        self._draw_pivoted(painter, self.assets.part_pixmap("arm_left"), "arm_left", pose.arm_left)
        self._draw_pivoted(painter, self.assets.part_pixmap("arm_right"), "arm_right", pose.arm_right)
        self._draw_pivoted(
            painter,
            self.assets.part_pixmap("torso"),
            "torso",
            pose.torso_twist,
            scale_y=breath,
        )
        # Only hand-held accessories are painted with the body.  There is no
        # torso garment layer any more, so a non-standard silhouette cannot
        # sprout a misplaced clothing rectangle.
        self.assets.draw_body_accessories(painter, self._accessories)

    def _paint_book(self, painter: QPainter) -> None:
        if self.assets.prop("book").isNull():
            return
        sway = math.sin(time.monotonic() * 2.3) * 1.5
        # The book is also a socket-mounted PNG; no hard-coded book geometry.
        self.assets.draw_prop(painter, "book", rotation=-3 + sway)

    def _paint_held_food(self, painter: QPainter) -> None:
        progress = min(
            1.0,
            max(
                0.0,
                (time.monotonic() - self._eat_started)
                / max(0.1, self._eat_end - self._eat_started),
            ),
        )
        if progress >= 0.78:
            return
        pixmap = self._food_pixmap
        if pixmap is None or pixmap.isNull():
            return
        wobble = math.sin(progress * math.tau * 4) * 3.0
        angle = -12 + progress * 20 + wobble
        scale = 1.0 + 0.04 * math.sin(progress * math.tau * 3) - 0.30 * progress
        # The mouth socket owns the position; this only animates the bite.
        self.assets.draw_food(
            painter,
            pixmap,
            self._food_item,
            scale=scale,
            rotation=angle,
        )

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        now = time.monotonic()
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        # Wipe the whole backing store to full transparency first.  Without
        # this an old frame can survive behind the sprite, which on some
        # drivers shows up as a faint tinted rectangle around the character.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if not self._godot_active:
            self._paint_character(painter, now)
        self._paint_sweat_drop(painter, now)
        if self._mode == Activity.RAGE.value:
            self._paint_rage_mark(painter, now)
        else:
            self._paint_combo_mark(painter, now)
        self._paint_particles(painter)
        if self._drop_hover:
            self._paint_drop_hint(painter)
        self._paint_bubble(painter, now)
        painter.end()

    def _paint_sweat_drop(self, painter: QPainter, now: float) -> None:
        """Paint a small ambient sweat drop above the head.

        This is deliberately outside the character texture: the held/panicked
        expression is communicated by an accessory-like overlay, never by
        painting fake eyes or a mouth onto ``head.png``.
        """

        if self._sweat_alpha <= 0.01:
            return
        path = self.catalog.sweat_file
        pixmap = self.common.pixmap(path)
        if pixmap.isNull():
            return
        hx, hy, hw, _hh = self.config.head_rect
        x = self._side + (hx + hw * 0.94) * self._pet_w
        y = self._top_space + (hy - 0.035) * self._pet_h
        bob = math.sin(now * 5.4) * 2.2
        size = max(12.0, self._pet_w * 0.105)
        painter.save()
        painter.setOpacity(self._sweat_alpha)
        painter.translate(x, y + bob)
        painter.rotate(12.0 + math.sin(now * 3.1) * 3.0)
        painter.drawPixmap(
            QRectF(-size / 2.0, -size / 2.0, size, size),
            pixmap,
            QRectF(pixmap.rect()),
        )
        painter.restore()

    def _paint_particles(self, painter: QPainter) -> None:
        for particle in self._particles:
            opacity = max(0.0, min(1.0, particle.life / max(0.01, particle.max_life)))
            painter.save()
            painter.setOpacity(opacity)
            painter.setPen(Qt.PenStyle.NoPen)
            if particle.kind == "heart":
                self._draw_heart(painter, particle.x, particle.y, particle.size, particle.colour)
            elif particle.kind == "sparkle":
                self._draw_sparkle(painter, particle.x, particle.y, particle.size, particle.colour)
            elif particle.kind == "zzz":
                painter.setFont(emoji_font(max(10, int(particle.size))))
                painter.setPen(particle.colour)
                painter.drawText(
                    QRectF(
                        particle.x - particle.size * 0.9,
                        particle.y - particle.size * 0.9,
                        particle.size * 1.8,
                        particle.size * 1.8,
                    ),
                    Qt.AlignmentFlag.AlignCenter,
                    particle.text or "💤",
                )
            elif particle.kind == "crumb":
                painter.setBrush(particle.colour)
                painter.drawEllipse(QPointF(particle.x, particle.y), particle.size, particle.size * 0.82)
            elif particle.kind == "dust":
                painter.setBrush(particle.colour)
                painter.drawEllipse(QPointF(particle.x, particle.y), particle.size, particle.size * 0.6)
            painter.restore()

    @staticmethod
    def _draw_heart(painter: QPainter, cx: float, cy: float, size: float, colour: QColor) -> None:
        path = QPainterPath()
        for i in range(49):
            t = math.tau * i / 48
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
            px = cx + x * size / 32
            py = cy + y * size / 32
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.closeSubpath()
        painter.setBrush(colour)
        painter.drawPath(path)

    @staticmethod
    def _draw_sparkle(painter: QPainter, cx: float, cy: float, size: float, colour: QColor) -> None:
        path = QPainterPath()
        path.moveTo(cx, cy - size)
        path.quadTo(cx + size * 0.18, cy - size * 0.18, cx + size, cy)
        path.quadTo(cx + size * 0.18, cy + size * 0.18, cx, cy + size)
        path.quadTo(cx - size * 0.18, cy + size * 0.18, cx - size, cy)
        path.quadTo(cx - size * 0.18, cy - size * 0.18, cx, cy - size)
        painter.setBrush(colour)
        painter.drawPath(path)

    def _paint_drop_hint(self, painter: QPainter) -> None:
        cx = self._side + self._pet_w / 2
        cy = self._top_space + self._pet_h * 0.44
        radius = self._pet_w * 0.38
        painter.save()
        pen = QPen(QColor(self.config.accent), 3.0, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap)
        pen.setDashPattern([5.0, 5.0])
        painter.setPen(pen)
        painter.setBrush(QColor(255, 255, 255, 16))
        painter.drawEllipse(QPointF(cx, cy), radius, radius * 0.85)
        label_rect = QRectF(cx - 66, cy - 14, 132, 28)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(55, 45, 56, 205))
        painter.drawRoundedRect(label_rect, 14, 14)
        painter.setPen(QColor(255, 250, 241))
        painter.setFont(font(10, QFont.Weight.DemiBold))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, "松手投喂")
        painter.restore()

    @staticmethod
    def _wrap_bubble_text(text: str, fm: QFontMetricsF, max_width: float) -> list[str]:
        """Greedy character wrap that behaves for both CJK and Latin text."""

        lines: list[str] = []
        for paragraph in str(text).splitlines() or [""]:
            paragraph = paragraph.rstrip()
            if not paragraph:
                lines.append("")
                continue
            current = ""
            for ch in paragraph:
                candidate = current + ch
                if current and fm.horizontalAdvance(candidate) > max_width:
                    cut = current.rfind(" ")
                    if cut >= max(1, len(current) // 3):
                        lines.append(current[:cut].rstrip())
                        current = current[cut + 1 :] + ch
                    else:
                        lines.append(current.rstrip())
                        current = ch.lstrip()
                else:
                    current = candidate
            if current:
                lines.append(current)
        if not lines:
            return [""]
        if len(lines) > 5:
            lines = lines[:5]
            last = lines[-1]
            while last and fm.horizontalAdvance(last + "…") > max_width:
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"
        return lines

    def _bubble_metrics(self, text: str) -> tuple[list[str], QFont, float, float]:
        max_text_width = max(118.0, min(282.0, self.width() - 66.0))
        chosen_lines: list[str] = [text]
        chosen_font = font(10.6, QFont.Weight.Medium)
        chosen_fm = QFontMetricsF(chosen_font)
        for size in (10.6, 10.0, 9.4, 8.8):
            candidate = font(size, QFont.Weight.Medium)
            metrics = QFontMetricsF(candidate)
            lines = self._wrap_bubble_text(text, metrics, max_text_width)
            height = metrics.lineSpacing() * len(lines) + 26.0
            chosen_lines, chosen_font, chosen_fm = lines, candidate, metrics
            if height <= self._top_space - 20:
                break
        content_width = max((chosen_fm.horizontalAdvance(line) for line in chosen_lines), default=52.0)
        bubble_w = min(self.width() - 24.0, max(112.0, content_width + 42.0))
        bubble_h = chosen_fm.lineSpacing() * len(chosen_lines) + 26.0
        return chosen_lines, chosen_font, bubble_w, bubble_h

    def _paint_bubble(self, painter: QPainter, now: float) -> None:
        bubble = self._bubble
        if not bubble:
            return
        alpha = bubble.alpha(now)
        if alpha <= 0.01:
            return
        elapsed = now - bubble.born
        lines, bfont, bubble_w, bubble_h = self._bubble_metrics(bubble.text)
        fm = QFontMetricsF(bfont)
        bx = (self.width() - bubble_w) / 2
        by = max(5.0, self._top_space - 17.0 - bubble_h)
        tail_x = max(bx + 27, min(bx + bubble_w - 27, self._side + self._pet_w / 2 + 2))
        top = max(4.0, by)
        tail_length = max(9.0, min(20.0, self._top_space - 4 - (top + bubble_h)))
        body = QPainterPath()
        body.addRoundedRect(QRectF(bx, top, bubble_w, bubble_h), 15, 15)
        tail = QPainterPath()
        tail.moveTo(tail_x - 9, top + bubble_h - 1.5)
        tail.lineTo(tail_x, top + bubble_h + tail_length)
        tail.lineTo(tail_x + 9, top + bubble_h - 1.5)
        tail.closeSubpath()
        comic = body.united(tail)

        intro = min(1.0, elapsed / 0.16)
        scale = 0.86 + 0.14 * intro
        # An ease-out pop anchored near the tail, so it "comes out" of the head.
        anchor_x, anchor_y = tail_x, top + bubble_h + tail_length
        painter.save()
        painter.setOpacity(alpha)
        painter.translate(anchor_x, anchor_y)
        painter.scale(scale, scale)
        painter.translate(-anchor_x, -anchor_y)

        # Crisp manga outline, no drop shadow: the bubble itself has to look
        # like ink on paper, not like another translucent window.
        painter.setPen(
            QPen(
                QColor(57, 47, 58, 255),
                2.2,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(QColor(255, 253, 247, 248))
        painter.drawPath(comic)

        # accent tab
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.config.accent))
        painter.drawRoundedRect(QRectF(bx + 12, top + 13, 4.0, max(12.0, bubble_h - 26)), 2, 2)
        painter.setFont(bfont)
        painter.setPen(QColor(56, 48, 59))
        text_x = bx + 25
        baseline = top + 13 + fm.ascent()
        for line in lines:
            painter.drawText(QPointF(text_x, baseline), line)
            baseline += fm.lineSpacing()
        painter.restore()

    # ------------------------------------------------------------------
    # mouse interaction
    # ------------------------------------------------------------------
    def _head_path_hit(self, local: QPointF) -> bool:
        hx, hy, hw, hh = self.config.head_rect
        dx = (local.x() - self._side) / self._pet_w
        if self._facing < 0:
            dx = 1.0 - dx
        dy = (local.y() - self._top_space) / self._pet_h
        if not (hx - 0.01 <= dx <= hx + hw + 0.01 and hy - 0.01 <= dy <= hy + hh + 0.01):
            return False
        cx = hx + hw / 2
        cy = hy + hh / 2
        nx = (dx - cx) / (hw / 2)
        ny = (dy - cy) / (hh / 2)
        return nx * nx + ny * ny <= 1.08

    def _body_hit(self, local: QPointF) -> bool:
        bx, by, bw, bh = self.config.body_rect
        dx = (local.x() - self._side) / self._pet_w
        if self._facing < 0:
            dx = 1.0 - dx
        dy = (local.y() - self._top_space) / self._pet_h
        return bx - 0.02 <= dx <= bx + bw + 0.02 and by - 0.01 <= dy <= by + bh + 0.02

    def _valid_press_point(self, local: QPointF) -> bool:
        return self._head_path_hit(local) or self._body_hit(local)

    def _interactive_local(self, local: QPointF) -> bool:
        if not self.rect().contains(local.toPoint()):
            return False
        if self._pressed or self._dragging or self._menu_open or self._drop_hover:
            return True
        return self._head_path_hit(local) or self._body_hit(local)

    def _poll_click_through(self, initial: bool = False) -> None:
        if not self.isVisible():
            return
        if not self._hwnd:
            if win32.IS_WINDOWS:
                self._hwnd = win32.pet_window_handle(self)
            if not self._hwnd:
                return
        if self._pressed or self._dragging or self._menu_open:
            should_pass = False
        elif self._drop_hover:
            should_pass = False
        else:
            local = QPointF(self.mapFromGlobal(QCursor.pos()))
            should_pass = not self._interactive_local(local)
        if should_pass != self._pass_through or initial:
            win32.set_click_through(self._hwnd, should_pass)
            self._pass_through = should_pass
        if not should_pass and not self._dragging:
            local = QPointF(self.mapFromGlobal(QCursor.pos()))
            if self._head_path_hit(local):
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            elif self._body_hit(local):
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self._dragging:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def enterEvent(self, event) -> None:  # noqa: N802, ANN001
        self._hover = True
        if self._mode in {Activity.WALK.value, Activity.SIT.value}:
            # Hover is an interaction too: abort the current hop/rest at once.
            self._interrupt_autonomy()
        if not self._dragging:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        self._hover = False
        if not self._pressed:
            self.unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            # Right-clicks are handled in contextMenuEvent; this avoids opening
            # the popup twice on platforms that synthesise both events.
            super().mousePressEvent(event)
            return
        if not self._valid_press_point(event.position()):
            event.ignore()
            return
        self.activate()
        self._interacted = True
        # Pressing on the pet is an immediate priority break: stop wandering
        # or sitting before a drag or poke is interpreted.
        self._interrupt_autonomy()
        self._press_global = event.globalPosition()
        self._press_local = event.position()
        self._drag_offset = self._press_global - QPointF(self.x(), self.y())
        self._pressed = True
        self._dragging = False
        self._drag_samples = [(time.monotonic(), self._press_global)]
        self._pointer_vx = 0.0
        self._pointer_vy = 0.0
        self._last_pointer_pos = self._press_global
        self._last_pointer_time = time.monotonic()
        self._woke_on_press = self._mode == Activity.SLEEP.value
        self._set_click_through(False)
        if self._woke_on_press:
            self.wake_up(by_user=True)
            self._woke_on_press = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._pressed or not (event.buttons() & Qt.MouseButton.LeftButton):
            if not self._dragging:
                local = event.position()
                if self._head_path_hit(local) or self._body_hit(local):
                    self.setCursor(Qt.CursorShape.OpenHandCursor)
                else:
                    self.unsetCursor()
            super().mouseMoveEvent(event)
            return
        global_pos = event.globalPosition()
        if not self._dragging:
            distance = (global_pos - self._press_global).manhattanLength()
            if distance >= QApplication.startDragDistance() + 2:
                self._begin_drag()
                self._last_pointer_pos = global_pos
                self._last_pointer_time = time.monotonic()
        if self._dragging:
            now = time.monotonic()
            elapsed = now - self._last_pointer_time
            if 0.004 <= elapsed <= 0.2:
                instant_x = (global_pos.x() - self._last_pointer_pos.x()) / elapsed
                instant_y = (global_pos.y() - self._last_pointer_pos.y()) / elapsed
                self._pointer_vx = self._pointer_vx * 0.42 + instant_x * 0.58
                self._pointer_vy = self._pointer_vy * 0.42 + instant_y * 0.58
            self._last_pointer_pos = global_pos
            self._last_pointer_time = now
            new_x = global_pos.x() - self._drag_offset.x()
            new_y = global_pos.y() - self._drag_offset.y()
            new_x, new_y = self._clamp_drag_position(new_x, new_y)
            self._x, self._y = new_x, new_y
            # Kept for the legacy body tilt and for the drop physics.
            self._vx = self._pointer_vx * 0.12
            self._vy = self._pointer_vy * 0.12
            self.move(round(self._x), round(self._y))
            self._drag_samples.append((time.monotonic(), global_pos))
            if len(self._drag_samples) > 8:
                del self._drag_samples[0]
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
        event.accept()

    def _begin_drag(self) -> None:
        if self._mode == Activity.RAGE.value or self._mode == Activity.SLEEP.value:
            return
        self._dragging = True
        self._cancel_study()
        self._food_pixmap = None
        self._food_item = None
        self._set_mode(Activity.DRAG.value)
        self._start_sweat()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._rng.random() < 0.62:
            self.say(self.config.pick_line("drag"), priority=1, voice_kind="poke")
        self._play_sfx("whoosh")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        was_dragging = self._dragging
        woke = self._woke_on_press
        local = event.position()
        if was_dragging:
            self._release_with_physics()
        elif self._pressed:
            if not woke and self._valid_press_point(local):
                if self._head_path_hit(local):
                    self.poke()
                else:
                    self._interacted = True
                    self.model.pulse(Expression.HAPPY.value, 0.6)
                    self._spawn_sparkles(1)
                    if not self._register_click():
                        self.say(self.config.pick_line("body"), priority=1)
        self._pressed = False
        self._dragging = False
        self._woke_on_press = False
        self._set_click_through(False)
        self._poll_click_through()
        self.setCursor(Qt.CursorShape.OpenHandCursor if self._valid_press_point(local) else Qt.CursorShape.ArrowCursor)
        event.accept()

    def _release_with_physics(self) -> None:
        vx = 0.0
        vy = 0.0
        if len(self._drag_samples) >= 2:
            t0, p0 = self._drag_samples[-2]
            t1, p1 = self._drag_samples[-1]
            elapsed = t1 - t0
            if 0.004 <= elapsed <= 0.25:
                vx = (p1.x() - p0.x()) / elapsed
                vy = (p1.y() - p0.y()) / elapsed
        vx = max(-1500.0, min(1500.0, vx))
        vy = max(-1300.0, min(1400.0, vy))
        self._vx = vx * 0.7
        self._vy = min(700.0, max(-200.0, vy * 0.6))
        self._landed_from_drag = True
        self._set_mode(Activity.FALL.value)
        if abs(vx) + abs(vy) > 650:
            self._play_sfx("whoosh")
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # A double-click is simply two pokes; avoid generating a drag start.
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        local = event.position()
        if not self._head_path_hit(local):
            event.ignore()
            return
        self.activate()
        self._interacted = True
        delta = event.angleDelta().y()
        steps = max(1, min(3, abs(delta) // 120 if delta else 1))
        for _ in range(steps):
            self.pat()
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802, ANN001
        self.activate()
        self._interrupt_autonomy()
        self._show_context_menu(event.globalPos())
        event.accept()

    def _show_context_menu(self, global_pos: QPoint) -> None:
        if self.manager is None:
            return
        menu = None
        try:
            menu = self.manager.build_context_menu(self)
            if menu is None:
                return
            self._menu_open = True
            self._set_click_through(False)
            menu.exec(global_pos)
        except Exception:
            log.exception("打开桌宠菜单失败")
        finally:
            self._menu_open = False
            if menu is not None:
                menu.deleteLater()

    # ------------------------------------------------------------------
    # drag & drop feeding
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if not (mime.hasUrls() or mime.hasText()):
            event.ignore()
            return
        if self._valid_press_point(event.position()):
            self._drop_hover = True
            self._menu_open = False
            self._set_click_through(False)
            self.update()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        inside = self._valid_press_point(event.position())
        self._drop_hover = inside
        if inside:
            event.acceptProposedAction()
        else:
            event.ignore()
        self.update()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802, ANN001
        self._drop_hover = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._drop_hover = False
        self.update()
        if not self._valid_press_point(event.position()):
            event.ignore()
            return
        mime = event.mimeData()
        path: Path | None = None
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    break
        if path is None:
            if mime.hasText():
                snippet = mime.text().strip().replace("\n", " ")[:30]
                self.activate()
                self.say(f"「{snippet}」……这串文字有点硌牙。" if snippet else "空的？你让我吃空气？", priority=2)
                self._spawn_sparkles(2)
                event.acceptProposedAction()
            else:
                event.ignore()
            return
        self.activate()
        self.feed_external(path)
        event.acceptProposedAction()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _set_click_through(self, enabled: bool) -> None:
        if not self._hwnd:
            return
        if enabled == self._pass_through:
            return
        if win32.set_click_through(self._hwnd, enabled):
            self._pass_through = enabled

    def _notify_closed(self) -> None:
        self.closed.emit(self)
