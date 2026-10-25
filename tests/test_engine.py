"""Pure-Python tests for the autonomous wandering state machine."""

from __future__ import annotations

import random
import unittest

from petapp.engine import (
    IDLE_DOODLES,
    ROAM_SPEED,
    SIT_DURATION_MAX,
    SIT_DURATION_MIN,
    WANDER_INTERVAL_MAX,
    WANDER_INTERVAL_MIN,
    AutonomousEngine,
    WanderAction,
)


class AutonomousEngineTests(unittest.TestCase):
    def test_idle_interval_is_eight_to_fifteen_seconds(self) -> None:
        engine = AutonomousEngine(random.Random(7))
        for _ in range(200):
            delay = engine.next_delay()
            self.assertGreaterEqual(delay, WANDER_INTERVAL_MIN)
            self.assertLessEqual(delay, WANDER_INTERVAL_MAX)

    def test_decisions_include_walk_sit_and_idle(self) -> None:
        engine = AutonomousEngine(random.Random(11))
        actions = {engine.decide(i).action for i in range(300)}
        self.assertEqual(
            actions,
            {WanderAction.WALK, WanderAction.SIT, WanderAction.IDLE},
        )

    def test_walk_is_slow_and_has_direction(self) -> None:
        engine = AutonomousEngine(random.Random(3))
        walks = [
            decision
            for decision in (engine.decide(i) for i in range(100))
            if decision.action == WanderAction.WALK
        ]
        self.assertTrue(walks)
        for decision in walks:
            self.assertEqual(decision.speed, ROAM_SPEED)
            self.assertIn(decision.direction, (-1, 1))
            self.assertGreaterEqual(decision.duration, WANDER_INTERVAL_MIN)
            self.assertLessEqual(decision.duration, WANDER_INTERVAL_MAX)

    def test_sit_duration_is_ten_to_twenty_seconds(self) -> None:
        engine = AutonomousEngine(random.Random(5))
        sits = [
            decision
            for decision in (engine.decide(i) for i in range(200))
            if decision.action == WanderAction.SIT
        ]
        self.assertTrue(sits)
        for decision in sits:
            self.assertGreaterEqual(decision.duration, SIT_DURATION_MIN)
            self.assertLessEqual(decision.duration, SIT_DURATION_MAX)
            self.assertEqual(decision.doodle, "")

    def test_idle_decisions_carry_one_doodle(self) -> None:
        engine = AutonomousEngine(random.Random(9))
        idles = [
            decision
            for decision in (engine.decide(i) for i in range(200))
            if decision.action == WanderAction.IDLE
        ]
        self.assertTrue(idles)
        for decision in idles:
            self.assertIn(decision.doodle, IDLE_DOODLES)
            self.assertGreaterEqual(decision.duration, WANDER_INTERVAL_MIN)
            self.assertLessEqual(decision.duration, WANDER_INTERVAL_MAX)

    def test_bust_mode_never_walks(self) -> None:
        engine = AutonomousEngine(random.Random(13))
        for i in range(200):
            decision = engine.decide(i, can_walk=False)
            self.assertNotEqual(decision.action, WanderAction.WALK)
            self.assertIn(
                decision.action,
                {WanderAction.SIT, WanderAction.IDLE},
            )


if __name__ == "__main__":
    unittest.main()
