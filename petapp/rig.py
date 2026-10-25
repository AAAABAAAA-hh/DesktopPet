"""Procedural joint animation for the paper-classmate puppets.

The character is painted as five pivotable layers (torso, two arms, two legs)
plus the head layer.  This module turns the window's state — walking, being
dragged, falling, landing, raging — into a small set of joint angles.  It is
pure Python and has no Qt imports, so the motion can be unit-tested without a
display.

The grabbed ("suspended") state is deliberately calm and weighty:

* horizontal pointer speed feeds a **damped spring** that produces a smooth
  inertial lean, hard-limited to ±10°;
* there is **no** 8 Hz squash pulse, no alternating body waddle and no
  per-frame limb flailing — those read as a mechanical buzz;
* a very slow vertical float (``motion.drag.bob_speed``, capped at 1.5 Hz)
  keeps the painting alive while it hangs still.

The panic/closed-eye expression is chosen by the window; this module only owns
geometry.  The numbers are in design-space pixels / degrees; the window
multiplies them by its display scale.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .motion import MotionProfile

TAU = math.tau


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _spring(value: float, velocity: float, target: float, stiffness: float, damping: float,
            dt: float) -> tuple[float, float]:
    """One semi-implicit Euler step of a damped spring."""

    velocity += ((target - value) * stiffness - velocity * damping) * dt
    value += velocity * dt
    return value, velocity


@dataclass(frozen=True)
class RigPose:
    """Joint angles for a single frame."""

    breath: float = 0.0
    bob: float = 0.0
    body_angle: float = 0.0
    torso_twist: float = 0.0
    head_tilt: float = 0.0
    head_bob: float = 0.0
    arm_left: float = 0.0
    arm_right: float = 0.0
    leg_left: float = 0.0
    leg_right: float = 0.0
    squash: float = 0.0
    stretch: float = 0.0
    #: How strongly the suspended pose is blended in (0..1).  Useful for
    #: tests and for fading the slow float out after release.
    drag: float = 0.0

    @property
    def scale_y(self) -> float:
        # Only the landing squash and the fall stretch may scale the sprite.
        # Dragging never applies a vertical squash pulse.
        return _clamp(1.0 + self.stretch * 0.75 - self.squash, 0.78, 1.18)

    @property
    def scale_x(self) -> float:
        # Squash and stretch preserve volume, so a squat gets a little wider.
        return _clamp(
            1.0 + self.squash * 0.55 - self.stretch * 0.35,
            0.84,
            1.16,
        )


class RagdollRig:
    """Spring-driven body/limb animation for one pet window."""

    BODY_STIFFNESS = 68.0
    BODY_DAMPING = 8.4
    LIMB_STIFFNESS = 44.0
    LIMB_DAMPING = 5.8
    HEAD_STIFFNESS = 118.0
    HEAD_DAMPING = 11.5
    SQUASH_STIFFNESS = 190.0
    SQUASH_DAMPING = 15.0
    #: Near-critical spring for the grabbed inertial lean.  The per-character
    #: ``drag.tilt_damping`` multiplier can make it a little softer/heavier,
    #: but it never becomes a snappy angle switch.
    DRAG_TILT_STIFFNESS = 46.0
    DRAG_TILT_DAMPING = 13.6
    MAX_BODY_ANGLE = 15.0
    MAX_LIMB_ANGLE = 40.0

    def __init__(
        self,
        seed: float = 0.0,
        profile: MotionProfile | None = None,
        canvas: tuple[float, float] | None = None,
    ) -> None:
        rng = random.Random(int(seed * 9973) + 17)
        self.phase = rng.uniform(0.0, TAU)
        self.profile = profile or MotionProfile()
        self.canvas = (360.0, 540.0) if canvas is None else (float(canvas[0]), float(canvas[1]))
        self._body = 0.0
        self._body_vel = 0.0
        self._head = 0.0
        self._head_vel = 0.0
        self._arms = [0.0, 0.0]
        self._arm_vel = [0.0, 0.0]
        self._legs = [0.0, 0.0]
        self._leg_vel = [0.0, 0.0]
        self._squash = 0.0
        self._squash_vel = 0.0
        self._stretch = 0.0
        self._vx = 0.0
        self._vy = 0.0
        self._drag_tilt = 0.0
        self._drag_tilt_vel = 0.0
        self._drag_blend = 0.0
        self._pose = RigPose()

    # ------------------------------------------------------------------
    # external impulses
    # ------------------------------------------------------------------
    def land(self, impact: float, *, bounce: bool = False) -> None:
        """Compress the doll when its feet hit the floor."""

        impact = max(0.0, float(impact))
        if bounce:
            amount = _clamp(impact / 6200.0, 0.004, 0.03)
            self._squash = max(self._squash, amount * 0.65)
            self._squash_vel = min(self._squash_vel, 0.0)
        else:
            # A "light squat": enough to read as weight, never a cartoon pancake.
            amount = _clamp(
                impact / 3000.0,
                self.profile.land_squash_min,
                self.profile.land_squash,
            )
            self._squash = max(self._squash, amount)
            self._squash_vel = 0.0

    def kick(self, strength: float = 1.0) -> None:
        """A tiny body shove, used by pokes and food rejects."""

        self._body_vel += 34.0 * _clamp(strength, -2.0, 2.0)

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------
    def update(
        self,
        dt: float,
        *,
        vx: float = 0.0,
        vy: float = 0.0,
        mode: str = "idle",
        now: float = 0.0,
        walk_gait: float = 0.0,
        direction: int = 1,
        climb_side: int = 0,
        sleeping: bool = False,
    ) -> RigPose:
        dt = _clamp(float(dt), 0.0, 0.08)
        if dt <= 0.0:
            return self._pose
        # Smooth the pointer velocity; mouse events are noisy and arrive in
        # bursts, which made the old tilt snap around.
        follow = min(1.0, dt * 14.0)
        self._vx += (float(vx) - self._vx) * follow
        self._vy += (float(vy) - self._vy) * follow

        body_target, head_target, torso_target = self._targets(
            mode, now, walk_gait, direction, climb_side, sleeping
        )
        arm_targets = self._limb_targets(
            mode, now, walk_gait, climbing=climb_side, sleeping=sleeping
        )
        leg_targets = self._leg_targets(mode, now, walk_gait, sleeping=sleeping)

        profile = self.profile
        # Only horizontal pointer speed drives the suspended lean.  The target
        # is negated so the body trails behind the hand (inertia) and is
        # hard-capped at ±12° before the damped spring smooths it.
        drag_target = 0.0
        if mode == "drag":
            drag_target = _clamp(
                -self._vx * profile.drag_tilt_gain,
                -profile.drag_tilt_max,
                profile.drag_tilt_max,
            )
        drag_damping = self.DRAG_TILT_DAMPING * profile.drag_tilt_damping

        steps = max(1, min(6, int(math.ceil(dt / 0.008))))
        h = dt / steps
        for _ in range(steps):
            self._body, self._body_vel = _spring(
                self._body, self._body_vel, body_target,
                self.BODY_STIFFNESS, self.BODY_DAMPING, h,
            )
            self._drag_tilt, self._drag_tilt_vel = _spring(
                self._drag_tilt, self._drag_tilt_vel, drag_target,
                self.DRAG_TILT_STIFFNESS, drag_damping, h,
            )
            self._head, self._head_vel = _spring(
                self._head, self._head_vel, head_target,
                self.HEAD_STIFFNESS, self.HEAD_DAMPING, h,
            )
            for i in range(2):
                self._arms[i], self._arm_vel[i] = _spring(
                    self._arms[i], self._arm_vel[i], arm_targets[i],
                    self.LIMB_STIFFNESS, self.LIMB_DAMPING, h,
                )
                self._legs[i], self._leg_vel[i] = _spring(
                    self._legs[i], self._leg_vel[i], leg_targets[i],
                    self.LIMB_STIFFNESS, self.LIMB_DAMPING, h,
                )
            self._squash, self._squash_vel = _spring(
                self._squash, self._squash_vel, 0.0,
                self.SQUASH_STIFFNESS, self.SQUASH_DAMPING, h,
            )
        self._stretch += (self._stretch_target(mode) - self._stretch) * min(1.0, dt * 9.0)
        if mode == "fall":
            body_limit = profile.fall_tilt
            head_limit = 12.0
        else:
            body_limit = self.MAX_BODY_ANGLE
            head_limit = 16.0
        self._body = _clamp(self._body, -body_limit, body_limit)
        self._drag_tilt = _clamp(
            self._drag_tilt,
            -profile.drag_tilt_max,
            profile.drag_tilt_max,
        )
        self._squash = _clamp(self._squash, 0.0, 0.2)
        self._stretch = _clamp(self._stretch, 0.0, 0.06)

        # Fade the held pose in/out so entering or leaving the grab is not a
        # pop.  Because the angle itself is spring-driven, direction changes
        # are always smooth as well.
        drag_blend_target = 1.0 if mode == "drag" else 0.0
        self._drag_blend += (drag_blend_target - self._drag_blend) * min(1.0, dt * 16.0)
        if self._drag_blend < 0.0005:
            self._drag_blend = 0.0
        drag_angle = self._drag_tilt * self._drag_blend

        breath_speed = profile.sleep_breath_speed if sleeping else profile.breath_speed
        breath = math.sin(now * breath_speed + self.phase)
        bob = self._bob(mode, now, breath, sleeping)
        head_bob = self._head_bob(mode, now, breath, sleeping)
        tilt = self._head + self._head_flourish(mode, now, walk_gait)
        torso_twist = _clamp(
            torso_target * 0.4 + self._body * 0.12 + math.sin(now * 1.1 + self.phase) * 0.3,
            -4.0,
            4.0,
        )
        if mode == "drag":
            # The whole painting floats slowly (1.5 Hz or less).  No vertical
            # squash, no limb oscillation, no head shake: just a calm hang.
            bob = (
                math.sin(now * TAU * profile.drag_bob_speed + self.phase)
                * profile.drag_bob
                * self._drag_blend
            )
            head_bob = 0.0
            tilt = 0.0
            torso_twist = 0.0
        body_angle = _clamp(self._body + drag_angle, -body_limit, body_limit)
        if mode == "drag":
            # The requirement is a hard ±12° envelope for the whole held
            # painting, including any residual idle sway being blended out.
            body_angle = _clamp(
                body_angle, -profile.drag_tilt_max, profile.drag_tilt_max
            )
        arm_left = _clamp(self._arms[0], -self.MAX_LIMB_ANGLE, self.MAX_LIMB_ANGLE)
        arm_right = _clamp(self._arms[1], -self.MAX_LIMB_ANGLE, self.MAX_LIMB_ANGLE)
        leg_left = _clamp(self._legs[0], -self.MAX_LIMB_ANGLE, self.MAX_LIMB_ANGLE)
        leg_right = _clamp(self._legs[1], -self.MAX_LIMB_ANGLE, self.MAX_LIMB_ANGLE)

        self._pose = RigPose(
            breath=breath,
            bob=bob,
            body_angle=body_angle,
            torso_twist=torso_twist,
            head_tilt=_clamp(tilt, -head_limit, head_limit),
            head_bob=head_bob,
            arm_left=arm_left,
            arm_right=arm_right,
            leg_left=leg_left,
            leg_right=leg_right,
            squash=self._squash,
            stretch=self._stretch,
            drag=self._drag_blend,
        )
        return self._pose

    @property
    def pose(self) -> RigPose:
        return self._pose

    # ------------------------------------------------------------------
    # targets per mode
    # ------------------------------------------------------------------
    def _targets(self, mode: str, now: float, walk_gait: float, direction: int,
                 climb_side: int, sleeping: bool) -> tuple[float, float, float]:
        body = 0.0
        head = 0.0
        torso = 0.0
        profile = self.profile
        if sleeping:
            return 0.0, 0.0, 0.0
        if mode == "drag":
            # The plain joint springs stay neutral while held.  The inertial
            # lean is a separate damped spring in update(); limbs never flail.
            return 0.0, 0.0, 0.0
        if mode == "fall":
            body = _clamp(
                self._vx * profile.fall_gain * 0.64,
                -profile.fall_tilt,
                profile.fall_tilt,
            ) + math.sin(now * 6.0 + self.phase) * profile.fall_sway
            head = _clamp(-body * 0.30 - self._vx * profile.fall_gain * 0.05, -6.0, 6.0)
            torso = body * 0.15
        elif mode == "climb":
            body = climb_side * 7.0 + math.sin(now * 5.5) * 1.0
            head = climb_side * 1.2
            torso = climb_side * 1.5
        elif mode == "walk":
            body = direction * 1.9 + math.sin(walk_gait * 2.0) * 1.2
            head = -math.sin(walk_gait) * 1.3
            torso = direction * 0.5
        elif mode == "rage":
            body = math.sin(now * 44.0) * 2.3
            head = math.sin(now * 37.0 + 0.7) * 2.4
            torso = math.sin(now * 51.0) * 0.8
        else:  # idle / eat / study
            body = math.sin(now * 1.55 + self.phase) * profile.idle_sway
            head = math.sin(now * 1.15 + self.phase + 0.9) * 0.6
            torso = math.sin(now * 1.2 + self.phase) * 0.4
        return body, head, torso

    def _limb_targets(self, mode: str, now: float, walk_gait: float,
                      *, climbing: int = 0, sleeping: bool = False) -> tuple[float, float]:
        if sleeping:
            return 0.0, 0.0
        if mode == "drag":
            # Overridden directly in update(); keep the springs near neutral.
            return 0.0, 0.0
        if mode == "fall":
            flutter = math.sin(now * 11.0 + self.phase) * 3.2
            base = -self._body * 0.45
            return base + 22.0 + flutter, base - 22.0 - flutter
        if mode == "climb":
            reach = math.sin(now * 7.5) * 8.0
            side = climbing or 1
            return (
                side * (20.0 + reach),
                side * (-20.0 + reach),
            )
        if mode == "walk":
            swing = math.sin(walk_gait) * 13.0
            return self._body * 0.4 + swing, self._body * 0.4 - swing
        if mode == "rage":
            jitter = math.sin(now * 31.0) * 5.0
            return 14.0 + jitter, -14.0 + jitter
        sway = math.sin(now * 1.45 + self.phase + 0.5) * 1.6
        return self._body * 0.35 + sway, self._body * 0.35 - sway

    def _leg_targets(self, mode: str, now: float, walk_gait: float,
                     *, sleeping: bool = False) -> tuple[float, float]:
        if sleeping:
            return 0.0, 0.0
        if mode == "drag":
            return 0.0, 0.0
        if mode == "fall":
            flutter = math.sin(now * 7.0 + self.phase + 1.1) * 2.0
            base = -self._body * 0.35
            return base + 5.0 + flutter, base - 5.0 - flutter
        if mode == "climb":
            phase = math.sin(now * 6.0)
            return 4.0 + phase * 3.0, 4.0 - phase * 3.0
        if mode == "walk":
            # A frontal paper doll has no knees to bend, so a small shuffle
            # reads better than a big stride that crosses the feet.
            swing = math.sin(walk_gait) * 8.0
            return -swing, swing
        if mode == "rage":
            return math.sin(now * 36.0) * 1.5, -math.sin(now * 36.0) * 1.5
        return 0.0, 0.0

    def _stretch_target(self, mode: str) -> float:
        if mode == "fall":
            return _clamp(self._vy / 3600.0, 0.0, 0.055)
        return 0.0

    # ------------------------------------------------------------------
    # cosmetic offsets
    # ------------------------------------------------------------------
    def _bob(self, mode: str, now: float, breath: float, sleeping: bool) -> float:
        if sleeping:
            return -breath * 0.9
        if mode == "drag":
            # The slow hang is added directly in update(); no 8 Hz pulse.
            return 0.0
        if mode == "fall":
            return math.sin(now * 6.0) * 0.6
        if mode == "walk":
            return -abs(math.sin(now * 7.2)) * 3.0
        if mode == "rage":
            return math.sin(now * 40.0) * 0.8
        # The chest rises a little more than it falls: a gentle inhale.
        return (
            -max(0.0, breath) * self.profile.breath_bob
            + math.sin(now * self.profile.breath_speed + self.phase) * 0.4
        )

    def _head_bob(self, mode: str, now: float, breath: float, sleeping: bool) -> float:
        if sleeping:
            return 0.0
        if mode == "drag":
            return 0.0
        if mode == "fall":
            return math.sin(now * 6.0 + 0.5) * 0.9
        if mode == "walk":
            return math.sin(now * 14.4) * 0.5
        if mode == "rage":
            return math.sin(now * 47.0) * 0.7
        # Head lags the chest by roughly a quarter of a breath.
        return -max(0.0, math.sin(now * 1.45 + self.phase - 0.55)) * 1.5

    def _head_flourish(self, mode: str, now: float, walk_gait: float) -> float:
        if mode == "walk":
            return -math.sin(walk_gait) * 1.2
        if mode == "drag":
            return 0.0
        if mode == "fall":
            return math.sin(now * 5.2 + self.phase) * 1.0
        if mode == "rage":
            return math.sin(now * 33.0) * 1.5
        if mode == "sleep":
            return 0.0
        return math.sin(now * 0.9 + self.phase) * 0.5
