from __future__ import annotations

import unittest
from pathlib import Path

from petapp.config import Catalog, load_characters
from petapp.model import Activity, Expression, PetModel

ROOT = Path(__file__).resolve().parents[1]


class PetModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = Catalog.load(ROOT / "assets" / "items")
        cls.characters = load_characters(ROOT / "characters")
        cls.config = cls.characters[0]

    def make_model(self) -> PetModel:
        return PetModel(self.config)

    def test_tick_makes_busy_and_hungry(self) -> None:
        model = self.make_model()
        hunger_before = model.hunger
        energy_before = model.energy
        for _ in range(60):
            model.tick(0.2)
        self.assertGreater(model.hunger, hunger_before)
        self.assertLess(model.energy, energy_before)
        self.assertGreaterEqual(model.hunger, 0.0)
        self.assertLessEqual(model.hunger, 100.0)

    def test_poke_and_pat(self) -> None:
        model = self.make_model()
        model.poke()
        self.assertGreater(model.anger, 0)
        self.assertEqual(model.face(), Expression.HIT.value)
        model.tick(2.0)
        before = model.anger
        model.pat()
        self.assertLess(model.anger, before)
        self.assertEqual(model.face(), Expression.HAPPY.value)

    def test_many_pokes_enable_rage_once(self) -> None:
        model = self.make_model()
        enabled = False
        for _ in range(60):
            if model.poke():
                enabled = True
                break
        self.assertTrue(enabled, "连续戳脸应该能充满怒气")
        self.assertTrue(model.can_rage())
        self.assertTrue(model.force_rage())
        self.assertEqual(model.activity, Activity.RAGE.value)
        self.assertGreater(model.rage_cooldown, 0)
        self.assertFalse(model.force_rage())
        model.finish_rage()
        self.assertLess(model.anger, 50)
        self.assertFalse(model.can_rage())

    def test_feed_and_reject(self) -> None:
        model = self.make_model()
        model.hunger = 80
        food = self.catalog.foods["drumstick"]
        outcome = model.feed(food)
        self.assertTrue(outcome.accepted)
        self.assertLess(model.hunger, 80)
        self.assertLess(outcome.hunger_delta, 0)
        model.reject_food()
        self.assertGreater(model.anger, 0)
        self.assertEqual(model.face(), Expression.ANGRY.value)

    def test_sleep_restores_energy(self) -> None:
        model = self.make_model()
        model.energy = 20
        model.begin_sleep()
        for _ in range(20):
            model.tick(0.2)
        self.assertGreater(model.energy, 20)
        self.assertEqual(model.face(), Expression.SLEEP.value)
        model.wake()
        self.assertNotEqual(model.face(), Expression.SLEEP.value)

    def test_drag_and_low_energy_expressions(self) -> None:
        model = self.make_model()
        model.set_activity(Activity.DRAG)
        self.assertEqual(model.face(), Expression.HIT.value)
        model.set_activity(Activity.IDLE)
        model.energy = 5
        self.assertEqual(model.face(), Expression.SLEEP.value)
        model.energy = 80
        model.hunger = 95
        self.assertEqual(model.face(), Expression.SAD.value)

    def test_blink_only_on_normal_face(self) -> None:
        model = self.make_model()
        self.assertEqual(model.face(blink=True), Expression.BLINK.value)
        model.pat()
        self.assertEqual(model.face(blink=True), Expression.HAPPY.value)


if __name__ == "__main__":
    unittest.main()
