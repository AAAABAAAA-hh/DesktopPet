"""Pure-Python tests for the shared click/combo motion curves."""

from __future__ import annotations

import unittest

from petapp.motion import BounceHop, ClickCombo, MotionProfile, TapBounce


class TapBounceTests(unittest.TestCase):
    def test_click_starts_at_five_percent_squash_and_settles(self) -> None:
        bounce = TapBounce()
        bounce.trigger(10.0)
        x, y = bounce.scales(10.0)
        self.assertAlmostEqual(x, 1.05, places=6)
        self.assertAlmostEqual(y, 0.95, places=6)
        self.assertTrue(bounce.active(10.0 + bounce.duration / 2))
        self.assertEqual(bounce.scales(10.0 + bounce.duration), (1.0, 1.0))
        self.assertEqual(bounce.scales(10.0 + bounce.duration + 1.0), (1.0, 1.0))

    def test_bounce_has_a_small_opposite_rebound(self) -> None:
        bounce = TapBounce()
        bounce.trigger(0.0)
        samples = [bounce.scales(bounce.duration * i / 100.0) for i in range(101)]
        self.assertLess(min(x for x, _ in samples), 1.0)
        self.assertGreater(max(y for _, y in samples), 1.0)

    def test_profile_can_tune_the_bounce(self) -> None:
        profile = MotionProfile.from_mapping(
            {"tap": {"duration": 0.24, "width": 0.09, "height": 0.04}}
        )
        bounce = TapBounce(
            duration=profile.tap_duration,
            width=profile.tap_width,
            height=profile.tap_height,
        )
        bounce.trigger(1.0)
        x, y = bounce.scales(1.0)
        self.assertAlmostEqual(x, 1.09, places=6)
        self.assertAlmostEqual(y, 0.96, places=6)
        self.assertTrue(bounce.active(1.2))
        self.assertFalse(bounce.active(1.25))


class BounceHopTests(unittest.TestCase):
    def test_charge_air_land_sequence(self) -> None:
        hop = BounceHop()
        crouch = hop.sample(0.01)
        self.assertLess(crouch.scale_y, 1.0, "起跳前应下蹲压缩")
        self.assertEqual(crouch.y_offset, 0.0)
        self.assertEqual(crouch.x_offset, 0.0)
        air = hop.sample(hop.crouch_time + hop.air_time / 2.0)
        self.assertLess(air.y_offset, 0.0, "腾空阶段应向上")
        self.assertGreater(air.x_offset, 0.0, "腾空阶段应向前")
        land = hop.sample(hop.crouch_time + hop.air_time + hop.land_time / 2.0)
        self.assertLess(land.scale_y, 1.0, "落地应有压缩回弹")
        self.assertEqual(land.y_offset, 0.0)
        done = hop.sample(hop.total_time + 0.01)
        self.assertTrue(done.completed)
        self.assertAlmostEqual(done.x_offset, hop.distance)
        self.assertEqual(done.scale_y, 1.0)

    def test_each_step_is_slow_and_has_a_grounded_rest(self) -> None:
        hop = BounceHop()
        self.assertGreaterEqual(hop.distance, 12.0)
        self.assertLessEqual(hop.distance, 18.0)
        self.assertGreaterEqual(hop.hop_time, 0.65)
        self.assertLessEqual(hop.hop_time, 0.75)
        self.assertGreaterEqual(hop.rest_time, 0.8)
        self.assertLessEqual(hop.rest_time, 1.2)
        self.assertGreaterEqual(hop.total_time, 1.45)
        self.assertLessEqual(hop.total_time, 1.95)
        self.assertEqual(hop.sample(hop.hop_time + 0.2).phase, "rest")
        self.assertEqual(hop.sample(hop.hop_time + 0.2).x_offset, hop.distance)

    def test_sixty_fps_sampling_is_smooth(self) -> None:
        hop = BounceHop()
        offsets = [
            hop.sample(i / 60.0).x_offset
            for i in range(int(hop.total_time * 60) + 1)
        ]
        steps = [b - a for a, b in zip(offsets, offsets[1:])]
        self.assertGreater(max(steps), 0.0)
        self.assertLess(max(steps), hop.distance * 0.25, "单帧位移不应跳变")


class ClickComboTests(unittest.TestCase):
    def test_three_rapid_taps_fire_once(self) -> None:
        combo = ClickCombo(threshold=3, window=0.9, cooldown=1.8)
        self.assertFalse(combo.tap(0.0))
        self.assertFalse(combo.tap(0.2))
        self.assertTrue(combo.tap(0.4))
        self.assertEqual(combo.count, 0)
        self.assertFalse(combo.tap(0.5), "冷却期间不能连续触发")

    def test_slow_taps_do_not_combo(self) -> None:
        combo = ClickCombo(threshold=3, window=0.5)
        combo.tap(0.0)
        combo.tap(0.4)
        self.assertFalse(combo.tap(0.9))

    def test_config_threshold_is_honoured(self) -> None:
        profile = MotionProfile.from_mapping(
            {"combo": {"threshold": 5, "window": 1.3, "cooldown": 2.0}}
        )
        combo = ClickCombo(
            threshold=profile.combo_threshold,
            window=profile.combo_window,
            cooldown=profile.combo_cooldown,
        )
        self.assertFalse(combo.tap(0.0))
        self.assertFalse(combo.tap(0.2))
        self.assertFalse(combo.tap(0.4))
        self.assertFalse(combo.tap(0.6))
        self.assertTrue(combo.tap(0.8))


class MotionProfileTests(unittest.TestCase):
    def test_defaults_are_sane_and_round_trip(self) -> None:
        profile = MotionProfile()
        self.assertGreater(profile.drag_tilt_gain, 0.0)
        self.assertLessEqual(profile.drag_tilt_max, 10.0)
        self.assertAlmostEqual(profile.drag_tilt_max, 10.0)
        self.assertGreater(profile.drag_tilt_damping, 0.0)
        self.assertGreaterEqual(profile.anchor_bob_hz, 1.2)
        self.assertLessEqual(profile.anchor_bob_hz, 1.5)
        self.assertGreater(profile.anchor_bob, 0.0)
        self.assertLessEqual(profile.drag_bob_speed, 1.5)
        self.assertGreater(profile.drag_bob, 0.0)
        self.assertEqual(profile.drag_panic_expression, "hit")
        self.assertGreater(profile.tap_width, 0)
        self.assertGreaterEqual(profile.combo_threshold, 2)
        mapping = profile.to_mapping()
        restored = MotionProfile.from_mapping(mapping)
        self.assertEqual(restored, profile)
        self.assertIn("drag", mapping)
        self.assertNotIn("dangle", mapping)

    def test_drag_parameters_come_from_config(self) -> None:
        profile = MotionProfile.from_mapping(
            {
                "drag": {
                    "tilt_gain": 0.02,
                    "tilt_max": 9.0,
                    "tilt_damping": 1.4,
                    "bob_speed": 1.25,
                    "bob": 2.8,
                    "panic_expression": "blink",
                }
            }
        )
        self.assertAlmostEqual(profile.drag_tilt_gain, 0.02)
        self.assertAlmostEqual(profile.drag_tilt_max, 9.0)
        self.assertAlmostEqual(profile.drag_tilt_damping, 1.4)
        self.assertAlmostEqual(profile.drag_bob_speed, 1.25)
        self.assertAlmostEqual(profile.drag_bob, 2.8)
        self.assertEqual(profile.drag_panic_expression, "blink")

    def test_bad_values_are_clamped_not_trusted(self) -> None:
        profile = MotionProfile.from_mapping(
            {
                "drag": {
                    "tilt_gain": 999,
                    "tilt_max": 90,
                    "tilt_damping": -1,
                    "bob_speed": 8.0,
                    "bob": -3,
                },
                "combo": {"threshold": 0, "window": -1},
                "tap": {"width": 9},
                "idle": {"anchor_bob_hz": 9.0, "anchor_bob": -2.0},
            }
        )
        self.assertLessEqual(profile.drag_tilt_gain, 0.05)
        self.assertLessEqual(profile.drag_tilt_max, 10.0)
        self.assertGreaterEqual(profile.drag_tilt_damping, 0.2)
        self.assertLessEqual(profile.drag_bob_speed, 1.5)
        self.assertLessEqual(profile.anchor_bob_hz, 1.5)
        self.assertGreaterEqual(profile.anchor_bob_hz, 1.2)
        self.assertEqual(profile.anchor_bob, 0.0)
        self.assertEqual(profile.drag_bob, 0.0)
        self.assertEqual(profile.combo_threshold, 2)
        self.assertGreater(profile.combo_window, 0.0)
        self.assertLessEqual(profile.tap_width, 0.20)

    def test_legacy_dangle_never_reintroduces_high_frequency_motion(self) -> None:
        profile = MotionProfile.from_mapping(
            {
                "dangle": {
                    "frequency": 8.0,
                    "squash": 0.04,
                    "sway": 0.02,
                    "panic_expression": "blink",
                },
                "drag": {"fall_tilt": 7.0},
            }
        )
        self.assertFalse(hasattr(profile, "dangle_frequency"))
        self.assertFalse(hasattr(profile, "dangle_squash"))
        self.assertFalse(hasattr(profile, "dangle_stretch"))
        self.assertEqual(profile.drag_panic_expression, "blink")
        self.assertLessEqual(profile.drag_bob_speed, 1.5)
        self.assertAlmostEqual(profile.fall_tilt, 7.0, msg="旧字段只保留落地/下落兼容")


if __name__ == "__main__":
    unittest.main()
