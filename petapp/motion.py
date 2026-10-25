"""Tactile interaction curves: click squash-and-stretch and rapid-tap combos.

The desktop-pet window needs two pieces of feel that are easier to reason about
(and test) outside Qt:

* :class:`TapBounce` turns one click into an instant 5% width / -5% height
  squash followed by a short, under-damped rebound.  It replaces the old
  random pixel shake, which read as a mechanical vibration rather than paper
  being pressed.
* :class:`ClickCombo` groups rapid taps into a combo so the window can show the
  angry "💢" reaction after three quick pokes.

The grabbed-in-the-air feel is deliberately **calm**: a damped inertial lean
driven by horizontal pointer speed (hard-limited to ±12°) plus a very slow
vertical float (≤1.5 Hz).  There is no 8 Hz squash pulse or per-frame limb
jitter any more; those made the painting buzz instead of feel heavy.

Everything here is pure Python and time is passed in explicitly; the unit tests
can drive it without a display.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class HopSample:
    """One sample of the 60 FPS bounce-hop cycle."""

    x_offset: float
    y_offset: float
    scale_x: float
    scale_y: float
    phase: str
    progress: float
    completed: bool


class BounceHop:
    """Charge → parabolic hop → elastic landing → grounded rest.

    The window still owns the actual screen position; this class supplies the
    vertical offset, squash/stretch and forward distance for one step.  The
    compression is deliberately gentle (0.95–1.02), the hop itself takes about
    0.64 s, and every landing is followed by a full 1.0 s of stationary rest so
    the pet never looks like it is chaining jittery jumps.
    """

    crouch_time: float = 0.12
    air_time: float = 0.42
    land_time: float = 0.12
    rest_time: float = 1.00
    distance: float = 15.0
    height: float = 12.0

    @property
    def hop_time(self) -> float:
        """Crouch + airborne + landing, without the grounded rest."""

        return self.crouch_time + self.air_time + self.land_time

    @property
    def hop_duration(self) -> float:
        """Public alias used by tuning/tests for the airborne step duration."""

        return self.hop_time

    @property
    def total_time(self) -> float:
        """Full cycle including the mandatory 1.0 s grounded rest."""

        return self.hop_time + self.rest_time

    @staticmethod
    def _ease(value: float) -> float:
        value = max(0.0, min(1.0, value))
        return value * value * (3.0 - 2.0 * value)

    def sample(self, elapsed: float) -> HopSample:
        """Return the pose for ``elapsed`` seconds into the current step."""

        elapsed = max(0.0, float(elapsed))
        if elapsed >= self.total_time:
            return HopSample(
                x_offset=self.distance,
                y_offset=0.0,
                scale_x=1.0,
                scale_y=1.0,
                phase="rest",
                progress=1.0,
                completed=True,
            )

        if elapsed < self.crouch_time:
            t = elapsed / max(1e-6, self.crouch_time)
            k = self._ease(t)
            return HopSample(0.0, 0.0, 1.0 + 0.02 * k, 1.0 - 0.04 * k, "crouch", t, False)

        air_end = self.crouch_time + self.air_time
        if elapsed < air_end:
            t = (elapsed - self.crouch_time) / max(1e-6, self.air_time)
            k = self._ease(t)
            arc = math.sin(math.pi * t)
            return HopSample(
                self.distance * k,
                -self.height * arc,
                1.0 - 0.01 * arc,
                1.0 + 0.02 * arc,
                "air",
                t,
                False,
            )

        land_end = air_end + self.land_time
        if elapsed < land_end:
            t = (elapsed - air_end) / max(1e-6, self.land_time)
            # Start landing gently squashed, then spring back to neutral.
            recover = self._ease(t)
            return HopSample(
                self.distance,
                0.0,
                1.02 - 0.02 * recover,
                0.95 + 0.05 * recover,
                "land",
                t,
                False,
            )

        t = (elapsed - land_end) / max(1e-6, self.rest_time)
        return HopSample(
            self.distance,
            0.0,
            1.0,
            1.0,
            "rest",
            t,
            False,
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _num(value: Any, fallback: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return _clamp(number, low, high)


def _integer(value: Any, fallback: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _expression(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


@dataclass(frozen=True)
class MotionProfile:
    """Per-character tuning for the shared motion engine.

    Every field has a safe default, so old character folders keep working.
    A character can override any subset in ``config.json``::

        "motion": {
          "idle": {"breath_speed": 1.3, "blink_interval": [2.2, 5.0]},
          "tap": {"width": 0.06, "height": 0.05, "duration": 0.16},
          "drag": {
            "tilt_gain": 0.012,
            "tilt_max": 12.0,
            "tilt_damping": 1.0,
            "bob_speed": 1.15,
            "bob": 2.2,
            "panic_expression": "hit"
          },
          "fall": {"tilt": 10, "gain": 0.014, "sway": 1.1},
          "land": {"squash": 0.1},
          "combo": {"threshold": 3, "window": 0.9, "angry_seconds": 2.2}
        }

    ``drag`` describes the suspended state.  ``tilt_gain`` converts horizontal
    pointer speed (pixels/second) into degrees, ``tilt_max`` hard-limits the
    lean to ±10° by default and ``tilt_damping`` scales the damped spring that
    smooths every direction change.  ``bob_speed`` is real-world Hz and is
    clamped to 1.5 Hz so the sprite can never buzz; ``bob`` is the design-space
    amplitude of that slow float.

    ``anchor_bob_hz`` / ``anchor_bob`` add the gentle 1.2–1.5 Hz whole-sprite
    breathing motion used while idle, seated or strolling.  The original clean
    head texture is never modified for a held/panic reaction.
    """

    # idle / blink
    breath_speed: float = 1.45
    breath_bob: float = 2.6
    idle_breath_scale: float = 0.006
    idle_breath_width: float = 0.0025
    idle_sway: float = 0.85
    #: Whole-anchor low-frequency float (1.2–1.5 Hz) for single-image pets.
    anchor_bob_hz: float = 1.3
    anchor_bob: float = 1.2
    blink_interval_min: float = 2.6
    blink_interval_max: float = 6.0
    blink_duration: float = 0.13
    # click squash
    tap_duration: float = 0.15
    tap_width: float = 0.05
    tap_height: float = 0.05
    # suspended drag: damped inertial lean + slow natural float
    drag_tilt_gain: float = 0.012
    drag_tilt_max: float = 10.0
    drag_tilt_damping: float = 1.0
    drag_bob_speed: float = 1.15
    drag_bob: float = 2.2
    #: Legacy config compatibility only.  The runtime communicates the held
    #: reaction with an ambient sweat drop and never changes the face texture.
    drag_panic_expression: str = "hit"
    # free fall
    fall_tilt: float = 10.0
    fall_gain: float = 0.014
    fall_sway: float = 1.1
    # landing
    land_squash: float = 0.11
    land_squash_min: float = 0.015
    # rapid-click reaction
    combo_threshold: int = 3
    combo_window: float = 0.9
    combo_cooldown: float = 1.8
    combo_mark_seconds: float = 1.25
    combo_angry_seconds: float = 2.2
    # sleeping
    sleep_breath_speed: float = 1.55
    sleep_breath_scale: float = 0.012
    sleep_breath_width: float = 0.0035

    @classmethod
    def from_mapping(cls, raw: Any) -> "MotionProfile":
        if not isinstance(raw, Mapping):
            return cls()

        def section(name: str) -> Mapping[str, Any]:
            value = raw.get(name)
            return value if isinstance(value, Mapping) else {}

        idle, tap = section("idle"), section("tap")
        # ``drag`` is the current section.  Older characters put their
        # panic-expression there under ``dangle``; that key is still read for
        # migration, but the old 8 Hz struggle parameters are intentionally
        # ignored (frequency / squash / sway / head shake / limb kicks).
        drag, land = section("drag"), section("land")
        legacy_dangle, fall = section("dangle"), section("fall")
        combo, sleep = section("combo"), section("sleep")
        blink = idle.get("blink_interval")
        if isinstance(blink, (list, tuple)) and len(blink) >= 2:
            blink_min = _num(blink[0], cls.blink_interval_min, 0.2, 120.0)
            blink_max = _num(blink[1], cls.blink_interval_max, 0.2, 180.0)
        else:
            blink_min = _num(idle.get("blink_min"), cls.blink_interval_min, 0.2, 120.0)
            blink_max = _num(idle.get("blink_max"), cls.blink_interval_max, 0.2, 180.0)
        if blink_max < blink_min:
            blink_min, blink_max = blink_max, blink_min

        return cls(
            breath_speed=_num(idle.get("breath_speed"), cls.breath_speed, 0.1, 8.0),
            breath_bob=_num(idle.get("breath_bob"), cls.breath_bob, 0.0, 12.0),
            idle_breath_scale=_num(
                idle.get("breath_scale"), cls.idle_breath_scale, 0.0, 0.04
            ),
            idle_breath_width=_num(
                idle.get("breath_width"), cls.idle_breath_width, 0.0, 0.02
            ),
            idle_sway=_num(idle.get("sway"), cls.idle_sway, 0.0, 8.0),
            anchor_bob_hz=_num(
                idle.get("anchor_bob_hz"), cls.anchor_bob_hz, 1.2, 1.5
            ),
            anchor_bob=_num(idle.get("anchor_bob"), cls.anchor_bob, 0.0, 4.0),
            blink_interval_min=blink_min,
            blink_interval_max=blink_max,
            blink_duration=_num(idle.get("blink_duration"), cls.blink_duration, 0.03, 0.8),
            tap_duration=_num(tap.get("duration"), cls.tap_duration, 0.04, 0.6),
            tap_width=_num(tap.get("width"), cls.tap_width, 0.0, 0.20),
            tap_height=_num(tap.get("height"), cls.tap_height, 0.0, 0.20),
            drag_tilt_gain=_num(
                drag.get("tilt_gain"), cls.drag_tilt_gain, 0.0, 0.05
            ),
            drag_tilt_max=_num(
                drag.get("tilt_max"), cls.drag_tilt_max, 0.0, 10.0
            ),
            drag_tilt_damping=_num(
                drag.get("tilt_damping"), cls.drag_tilt_damping, 0.2, 2.0
            ),
            drag_bob_speed=_num(
                drag.get("bob_speed"), cls.drag_bob_speed, 0.1, 1.5
            ),
            drag_bob=_num(drag.get("bob"), cls.drag_bob, 0.0, 8.0),
            drag_panic_expression=_expression(
                drag.get(
                    "panic_expression",
                    legacy_dangle.get("panic_expression", cls.drag_panic_expression),
                ),
                cls.drag_panic_expression,
            ),
            fall_tilt=_num(
                fall.get(
                    "tilt",
                    _num(drag.get("fall_tilt"), cls.fall_tilt, 0.0, 30.0),
                ),
                cls.fall_tilt,
                0.0,
                30.0,
            ),
            fall_gain=_num(fall.get("gain"), cls.fall_gain, 0.0, 0.08),
            fall_sway=_num(fall.get("sway"), cls.fall_sway, 0.0, 8.0),
            land_squash=_num(land.get("squash"), cls.land_squash, 0.0, 0.25),
            land_squash_min=_num(land.get("min"), cls.land_squash_min, 0.0, 0.10),
            combo_threshold=_integer(combo.get("threshold"), cls.combo_threshold, 2, 12),
            combo_window=_num(combo.get("window"), cls.combo_window, 0.15, 5.0),
            combo_cooldown=_num(combo.get("cooldown"), cls.combo_cooldown, 0.0, 30.0),
            combo_mark_seconds=_num(
                combo.get("mark_seconds"), cls.combo_mark_seconds, 0.2, 6.0
            ),
            combo_angry_seconds=_num(
                combo.get("angry_seconds"), cls.combo_angry_seconds, 0.2, 12.0
            ),
            sleep_breath_speed=_num(
                sleep.get("breath_speed"), cls.sleep_breath_speed, 0.1, 6.0
            ),
            sleep_breath_scale=_num(
                sleep.get("breath_scale"), cls.sleep_breath_scale, 0.0, 0.06
            ),
            sleep_breath_width=_num(
                sleep.get("breath_width"), cls.sleep_breath_width, 0.0, 0.03
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Canonical ``config.json`` representation for new characters."""

        return {
            "idle": {
                "breath_speed": self.breath_speed,
                "breath_bob": self.breath_bob,
                "breath_scale": self.idle_breath_scale,
                "breath_width": self.idle_breath_width,
                "sway": self.idle_sway,
                "anchor_bob_hz": self.anchor_bob_hz,
                "anchor_bob": self.anchor_bob,
                "blink_interval": [self.blink_interval_min, self.blink_interval_max],
                "blink_duration": self.blink_duration,
            },
            "tap": {
                "duration": self.tap_duration,
                "width": self.tap_width,
                "height": self.tap_height,
            },
            "drag": {
                "tilt_gain": self.drag_tilt_gain,
                "tilt_max": self.drag_tilt_max,
                "tilt_damping": self.drag_tilt_damping,
                "bob_speed": self.drag_bob_speed,
                "bob": self.drag_bob,
                "panic_expression": self.drag_panic_expression,
            },
            "fall": {
                "tilt": self.fall_tilt,
                "gain": self.fall_gain,
                "sway": self.fall_sway,
            },
            "land": {
                "squash": self.land_squash,
                "min": self.land_squash_min,
            },
            "combo": {
                "threshold": self.combo_threshold,
                "window": self.combo_window,
                "cooldown": self.combo_cooldown,
                "mark_seconds": self.combo_mark_seconds,
                "angry_seconds": self.combo_angry_seconds,
            },
            "sleep": {
                "breath_speed": self.sleep_breath_speed,
                "breath_scale": self.sleep_breath_scale,
                "breath_width": self.sleep_breath_width,
            },
        }


class TapBounce:
    """A short squash-and-rebound used for clicks and small hits.

    ``scales(now)`` returns ``(scale_x, scale_y)`` for the whole sprite.  At the
    instant of the trigger it is exactly ``(1.05, 0.95)``; the envelope then
    passes through a small opposite stretch (the Q-bounce) and is exactly
    ``(1.0, 1.0)`` after ``duration`` seconds.
    """

    DURATION = 0.15
    WIDTH = 0.05
    HEIGHT = 0.05

    def __init__(
        self,
        duration: float = DURATION,
        width: float = WIDTH,
        height: float = HEIGHT,
    ) -> None:
        self.duration = max(0.02, float(duration))
        self.width = max(0.0, float(width))
        self.height = max(0.0, float(height))
        self._started = -1e9
        self._strength = 1.0

    def trigger(self, now: float, strength: float = 1.0) -> None:
        """Restart the bounce at ``now``.

        The strength scales both axes, clamped so a stray event can never turn
        the sprite inside out (or into a pancake).
        """

        self._started = float(now)
        self._strength = _clamp(float(strength), 0.0, 2.0)

    def scales(self, now: float) -> tuple[float, float]:
        elapsed = float(now) - self._started
        if elapsed < 0.0 or elapsed >= self.duration:
            return 1.0, 1.0
        t = elapsed / self.duration
        # (1 - t)^2 makes the return land smoothly at exactly zero, while the
        # cosine adds one controlled overshoot through the opposite squash.
        envelope = (1.0 - t) ** 2 * math.cos(t * math.pi * 1.55)
        return (
            1.0 + self.width * self._strength * envelope,
            1.0 - self.height * self._strength * envelope,
        )

    def active(self, now: float) -> bool:
        return 0.0 <= float(now) - self._started < self.duration

    def reset(self) -> None:
        self._started = -1e9
        self._strength = 1.0


class ClickCombo:
    """Count rapid taps and fire once when the threshold is reached.

    A combo is ``threshold`` taps whose first and last are at most ``window``
    seconds apart.  After firing, the tracker clears and ignores taps for
    ``cooldown`` seconds so an angry reaction cannot stack every frame.
    """

    def __init__(
        self,
        *,
        threshold: int = 3,
        window: float = 0.9,
        cooldown: float = 1.8,
    ) -> None:
        self.threshold = max(2, int(threshold))
        self.window = max(0.1, float(window))
        self.cooldown = max(0.0, float(cooldown))
        self._taps: list[float] = []
        self._cooldown_until = -1e9

    @property
    def count(self) -> int:
        return len(self._taps)

    def tap(self, now: float) -> bool:
        """Record one tap and return True when a combo just fired."""

        now = float(now)
        if now < self._cooldown_until:
            return False
        self._taps = [stamp for stamp in self._taps if now - stamp <= self.window]
        self._taps.append(now)
        if len(self._taps) < self.threshold:
            return False
        self._taps.clear()
        self._cooldown_until = now + self.cooldown
        return True

    def reset(self) -> None:
        self._taps.clear()
