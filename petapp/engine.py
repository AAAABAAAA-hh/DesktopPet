"""Autonomous wandering state machine for the desktop pet.

The window owns the physical window, painting and Qt timers; this module owns
the *decision* part: when an idle classmate should wander, sit down, or simply
doodle in place.  Keeping it pure Python makes the 8–15 second cadence and the
30 px/s roaming rules easy to test without a display.

The only inputs are a monotonic clock (the caller passes ``now``), whether the
character is allowed to walk (``bust_mode`` portraits cannot), and an optional
RNG.  Outputs are small immutable decisions the window applies.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

#: Idle time between two autonomous decisions.  The requirement is 8–15 s.
WANDER_INTERVAL_MIN = 8.0
WANDER_INTERVAL_MAX = 15.0

#: A seated rest lasts noticeably longer than the gap between decisions.
SIT_DURATION_MIN = 10.0
SIT_DURATION_MAX = 20.0

#: Edge-roaming speed.  Slow enough to read as a paper doll strolling along
#: the taskbar, not as a runaway window.
ROAM_SPEED = 30.0

#: Small in-place actions chosen for the stand-and-idle branch.
IDLE_DOODLES = ("blink", "tilt", "sigh")


class WanderAction(str, Enum):
    IDLE = "idle"
    WALK = "walk"
    SIT = "sit"


@dataclass(frozen=True)
class WanderDecision:
    """One autonomous transition selected for the window."""

    action: WanderAction
    direction: int = 1
    duration: float = WANDER_INTERVAL_MIN
    speed: float = ROAM_SPEED
    doodle: str = ""

    @property
    def is_walk(self) -> bool:
        return self.action == WanderAction.WALK

    @property
    def is_sit(self) -> bool:
        return self.action == WanderAction.SIT


class AutonomousEngine:
    """Select the next idle behaviour on an 8–15 second cadence."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()

    def next_delay(self) -> float:
        return self.rng.uniform(WANDER_INTERVAL_MIN, WANDER_INTERVAL_MAX)

    def decide(self, now: float, *, can_walk: bool = True) -> WanderDecision:
        """Choose the next action.

        Walking is the most common branches for a normal standing character;
        seated rest is a little less frequent; standing doodles fill the rest.
        Bust-mode portraits never walk, so they split between sitting and
        fidgeting in place.
        """

        _ = now  # kept in the signature for callers that schedule by clock
        if can_walk:
            roll = self.rng.random()
            if roll < 0.50:
                return WanderDecision(
                    action=WanderAction.WALK,
                    direction=self.rng.choice((-1, 1)),
                    duration=self.next_delay(),
                    speed=ROAM_SPEED,
                )
            if roll < 0.80:
                return WanderDecision(
                    action=WanderAction.SIT,
                    duration=self.rng.uniform(SIT_DURATION_MIN, SIT_DURATION_MAX),
                )
        elif self.rng.random() < 0.45:
            return WanderDecision(
                action=WanderAction.SIT,
                duration=self.rng.uniform(SIT_DURATION_MIN, SIT_DURATION_MAX),
            )

        return WanderDecision(
            action=WanderAction.IDLE,
            duration=self.next_delay(),
            doodle=self.rng.choice(IDLE_DOODLES),
        )
