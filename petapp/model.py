"""Pure-Python personality model (no Qt imports, unit-testable)."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from .config import CharacterConfig, FoodItem


class Expression(str, Enum):
    NORMAL = "normal"
    BLINK = "blink"
    HAPPY = "happy"
    ANGRY = "angry"
    HIT = "hit"
    SLEEP = "sleep"
    EAT = "eat"
    SAD = "sad"
    SMUG = "smug"


class Activity(str, Enum):
    IDLE = "idle"
    WALK = "walk"
    SIT = "sit"
    DRAG = "drag"
    FALL = "fall"
    CLIMB = "climb"
    SLEEP = "sleep"
    EAT = "eat"
    STUDY = "study"
    RAGE = "rage"


@dataclass
class FeedOutcome:
    accepted: bool
    hunger_delta: float = 0.0
    energy_delta: float = 0.0
    anger_delta: float = 0.0
    line_kind: str = "feed"


@dataclass
class PetModel:
    config: CharacterConfig
    rng: random.Random = field(default_factory=random.Random)
    anger: float = 0.0
    hunger: float = 24.0
    energy: float = 82.0
    bond: float = 0.0
    age: float = 0.0
    activity: str = Activity.IDLE.value
    pulse_expression: str = ""
    pulse_remaining: float = 0.0
    rage_cooldown: float = 0.0
    pokes: int = 0

    # ------------------------------------------------------------------
    # stats
    # ------------------------------------------------------------------
    def _clamp(self) -> None:
        self.anger = max(0.0, min(100.0, self.anger))
        self.hunger = max(0.0, min(100.0, self.hunger))
        self.energy = max(0.0, min(100.0, self.energy))
        self.bond = max(0.0, min(100.0, self.bond))

    def set_activity(self, activity: str | Activity) -> None:
        self.activity = activity.value if isinstance(activity, Activity) else str(activity)

    def tick(self, dt: float) -> None:
        if dt <= 0:
            return
        dt = min(dt, 0.2)
        self.age += dt
        self.rage_cooldown = max(0.0, self.rage_cooldown - dt)
        if self.pulse_remaining > 0:
            self.pulse_remaining = max(0.0, self.pulse_remaining - dt)
            if self.pulse_remaining == 0:
                self.pulse_expression = ""

        if self.activity == Activity.SLEEP.value:
            self.energy += 8.0 * dt
            self.hunger += 0.022 * dt
            self.anger = max(0.0, self.anger - 0.05 * dt)
        else:
            self.energy -= 0.035 * dt
            self.hunger += 0.06 * dt
            if self.activity not in {Activity.DRAG.value, Activity.FALL.value, Activity.RAGE.value}:
                self.anger = max(0.0, self.anger - 0.14 * dt)
        if self.hunger > 94:
            self.anger += 0.08 * dt
        self._clamp()

    def pulse(self, expression: str, duration: float = 0.8) -> None:
        if expression:
            self.pulse_expression = expression
            self.pulse_remaining = max(0.0, duration)

    # ------------------------------------------------------------------
    # interactions
    # ------------------------------------------------------------------
    def poke(self) -> bool:
        """Poke the face. Returns True when rage just became available."""

        self.pokes += 1
        weight = 7.2 * self.config.temper
        if self.hunger > 70:
            weight += 0.6
        if self.energy < 20:
            weight += 0.5
        self.anger += weight
        self.bond = max(0.0, self.bond - 0.15)
        self.pulse(Expression.HIT.value, 0.75)
        self._clamp()
        return self.can_rage()

    def pat(self) -> None:
        self.anger = max(0.0, self.anger - 6.4)
        self.bond = min(100.0, self.bond + 1.2)
        self.energy = min(100.0, self.energy + 0.3)
        self.pulse(Expression.HAPPY.value, 1.0)
        self._clamp()

    def begin_sleep(self) -> None:
        self.set_activity(Activity.SLEEP)
        self.pulse("", 0.0)

    def wake(self) -> None:
        if self.activity == Activity.SLEEP.value:
            self.set_activity(Activity.IDLE)

    def feed(self, food: FoodItem) -> FeedOutcome:
        old_hunger = self.hunger
        self.hunger -= max(0.0, food.hunger)
        self.energy += food.energy
        self.anger += food.anger
        self.bond = min(100.0, self.bond + 0.8)
        self._clamp()
        if food.anger > 0:
            self.pulse(Expression.HIT.value, 1.0)
        else:
            self.pulse(Expression.HAPPY.value, 1.0)
        return FeedOutcome(
            accepted=True,
            hunger_delta=self.hunger - old_hunger,
            energy_delta=food.energy,
            anger_delta=food.anger,
            line_kind="feed",
        )

    def eat_external(self, hunger: float = 16.0, energy: float = 2.0) -> FeedOutcome:
        old_hunger = self.hunger
        self.hunger = max(0.0, self.hunger - hunger)
        self.energy = min(100.0, self.energy + energy)
        self.bond = min(100.0, self.bond + 0.5)
        self.pulse(Expression.HAPPY.value, 1.0)
        self._clamp()
        return FeedOutcome(
            accepted=True,
            hunger_delta=self.hunger - old_hunger,
            energy_delta=energy,
            line_kind="file_eat",
        )

    def reject_food(self) -> None:
        self.anger = min(100.0, self.anger + 5.5)
        self.pulse(Expression.ANGRY.value, 1.0)
        self._clamp()

    # ------------------------------------------------------------------
    # rage
    # ------------------------------------------------------------------
    def can_rage(self) -> bool:
        return self.rage_cooldown <= 0 and self.anger >= self.config.rage_threshold

    def force_rage(self) -> bool:
        if self.rage_cooldown > 0:
            return False
        self.rage_cooldown = 80.0
        self.anger = 100.0
        self.set_activity(Activity.RAGE)
        self.pulse_expression = ""
        self.pulse_remaining = 0.0
        return True

    def finish_rage(self) -> None:
        self.anger = min(self.anger, 45.0)
        self.rage_cooldown = max(self.rage_cooldown, 70.0)
        self.set_activity(Activity.IDLE)
        self._clamp()

    # ------------------------------------------------------------------
    # presentation
    # ------------------------------------------------------------------
    def face(self, blink: bool = False) -> str:
        if self.activity in {Activity.DRAG.value, Activity.FALL.value, Activity.CLIMB.value}:
            return Expression.HIT.value
        if self.activity == Activity.SLEEP.value:
            return Expression.SLEEP.value
        if self.activity == Activity.EAT.value:
            return Expression.EAT.value
        if self.activity == Activity.RAGE.value or self.anger >= 70:
            return Expression.ANGRY.value
        if self.pulse_remaining > 0 and self.pulse_expression:
            return self.pulse_expression
        if self.hunger >= 88:
            return Expression.SAD.value
        if self.energy <= 12 and self.activity not in {Activity.STUDY.value}:
            return Expression.SLEEP.value
        if blink:
            return Expression.BLINK.value
        return Expression.NORMAL.value

    def mood_label(self) -> str:
        if self.activity == Activity.SLEEP.value:
            return "睡得正香"
        if self.activity == Activity.RAGE.value:
            return "怒火中烧"
        if self.activity in {Activity.DRAG.value, Activity.FALL.value}:
            return "腾空失重"
        if self.activity == Activity.SIT.value:
            return "坐着歇会儿"
        if self.activity == Activity.STUDY.value:
            return "假装学习"
        if self.anger >= 70:
            return "气鼓鼓"
        if self.hunger >= 88:
            return "饿扁了"
        if self.energy <= 15:
            return "困成纸片"
        if self.pulse_remaining > 0 and self.pulse_expression == Expression.HAPPY.value:
            return "心情不错"
        return "平静摸鱼"

    def stat_line(self) -> str:
        return (
            f"{self.mood_label()} · 火气 {int(round(self.anger))}% · "
            f"饱腹 {int(round(100 - self.hunger))}% · 电量 {int(round(self.energy))}%"
        )

    def is_hungry(self) -> bool:
        return self.hunger >= 88

    def is_exhausted(self) -> bool:
        return self.energy <= 12

    def awake(self) -> bool:
        return self.activity != Activity.SLEEP.value

    def pick_line(self, kind: str, fallback: str = "idle") -> str:
        return self.config.pick_line(kind, fallback, self.rng)
