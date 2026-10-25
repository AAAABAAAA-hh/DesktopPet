"""Pure-Python tests for the joint animation model (no Qt, no display)."""

from __future__ import annotations

import math
import unittest

from petapp.rig import RagdollRig


class RigTests(unittest.TestCase):
    def test_idle_breath_stays_gentle(self) -> None:
        rig = RagdollRig(0.7)
        bobs = []
        for frame in range(360):
            pose = rig.update(1 / 60, mode="idle", now=frame / 60)
            bobs.append(pose.bob)
            self.assertTrue(math.isfinite(pose.body_angle))
            self.assertLessEqual(abs(pose.body_angle), 3.0)
            self.assertLessEqual(abs(pose.head_tilt), 3.0)
        self.assertGreater(max(bobs) - min(bobs), 1.5, "呼吸应该有肉眼可见的上下浮动")
        self.assertLess(max(bobs) - min(bobs), 6.0, "呼吸幅度不能像蹦迪")

    def test_drag_uses_smooth_damped_tilt_bounded_to_12_degrees(self) -> None:
        rig = RagdollRig(0.2)
        angles: list[float] = []
        for frame in range(180):
            # Alternate direction every second: the angle must ease across,
            # never snap from one sign to the other.
            vx = 1600 if (frame // 60) % 2 == 0 else -1600
            pose = rig.update(1 / 60, vx=vx, mode="drag", now=frame / 60)
            angles.append(pose.body_angle)
            self.assertLessEqual(abs(pose.body_angle), 10.0 + 1e-6)
            self.assertEqual(pose.squash, 0.0, "拖拽不再有垂直 squash")
            self.assertEqual(pose.scale_y, 1.0, "拖拽不再改变立绘高度")
        self.assertGreater(max(angles), 3.0, "水平速度应该产生可见的惯性倾角")
        self.assertLess(min(angles), -3.0)
        biggest_step = max(abs(b - a) for a, b in zip(angles, angles[1:]))
        self.assertLess(biggest_step, 2.5, "倾角必须由阻尼平滑过渡，而不是硬切")

    def test_suspended_bob_is_low_frequency(self) -> None:
        from petapp.motion import MotionProfile

        for speed in (0.8, 1.15, 1.5, 8.0):
            profile = MotionProfile.from_mapping(
                {"drag": {"bob_speed": speed, "bob": 2.2}}
            )
            self.assertLessEqual(profile.drag_bob_speed, 1.5)
            rig = RagdollRig(0.5, profile=profile)
            samples: list[float] = []
            start = 0.6  # let the blend-in finish
            for frame in range(360):  # 3 seconds at 120 Hz
                now = start + frame / 120
                pose = rig.update(1 / 120, vx=0, mode="drag", now=now)
                samples.append(pose.bob)
            crossings = sum(
                1
                for a, b in zip(samples, samples[1:])
                if (a <= 0.0 < b) or (a >= 0.0 > b)
            )
            measured_hz = crossings / 2.0 / 3.0
            self.assertLessEqual(measured_hz, 1.5 + 0.15)
            self.assertGreater(max(samples) - min(samples), 1.0, "应该有轻微自然浮动")

    def test_drag_has_no_limb_or_head_jitter(self) -> None:
        rig = RagdollRig(0.4)
        for frame in range(180):
            pose = rig.update(1 / 60, vx=1400, vy=600, mode="drag", now=frame / 60)
            self.assertEqual(pose.arm_left, 0.0)
            self.assertEqual(pose.arm_right, 0.0)
            self.assertEqual(pose.leg_left, 0.0)
            self.assertEqual(pose.leg_right, 0.0)
            self.assertEqual(pose.head_tilt, 0.0)
            self.assertEqual(pose.head_bob, 0.0)

    def test_motion_profile_overrides_drag_tuning(self) -> None:
        from petapp.motion import MotionProfile

        profile = MotionProfile.from_mapping(
            {"drag": {"tilt_gain": 0.005, "tilt_max": 6.0, "bob": 1.0}}
        )
        rig = RagdollRig(0.5, profile=profile)
        angles = []
        bobs = []
        for frame in range(180):
            pose = rig.update(1 / 60, vx=1400, mode="drag", now=frame / 60)
            angles.append(pose.body_angle)
            bobs.append(pose.bob)
        self.assertLessEqual(max(abs(v) for v in angles), 6.0 + 1e-6)
        self.assertLessEqual(max(abs(v) for v in bobs), 1.0 + 1e-6)

    def test_landing_squashes_then_recovers(self) -> None:
        rig = RagdollRig(0.1)
        rig.land(520.0)
        pose = rig.update(1 / 60, mode="idle", now=0.0)
        self.assertGreater(pose.squash, 0.05)
        self.assertLess(pose.scale_y, 0.97)
        self.assertGreater(pose.scale_x, 1.005)
        for frame in range(120):
            pose = rig.update(1 / 60, mode="idle", now=frame / 60)
        self.assertLess(pose.squash, 0.01, "回弹后应该恢复站姿")
        self.assertAlmostEqual(pose.scale_y, 1.0, delta=0.02)
        self.assertAlmostEqual(pose.scale_x, 1.0, delta=0.02)

    def test_fall_stretches_and_walk_alternates_legs(self) -> None:
        rig = RagdollRig(0.9)
        for frame in range(40):
            pose = rig.update(1 / 60, vx=250, vy=950, mode="fall", now=frame / 60)
        self.assertGreater(pose.stretch, 0.02)
        self.assertGreater(pose.scale_y, 1.01)

        walker = RagdollRig(0.3)
        for frame in range(40):
            first = walker.update(1 / 60, mode="walk", now=frame / 60, walk_gait=math.pi / 2)
        self.assertLess(first.leg_left, 0.0)
        self.assertGreater(first.leg_right, 0.0)
        for frame in range(40):
            second = walker.update(
                1 / 60, mode="walk", now=1 + frame / 60, walk_gait=3 * math.pi / 2
            )
        self.assertGreater(second.leg_left, 0.0)
        self.assertLess(second.leg_right, 0.0)

    def test_all_modes_stay_bounded(self) -> None:
        for mode in ("idle", "walk", "drag", "fall", "climb", "rage", "eat", "study"):
            rig = RagdollRig(0.5)
            for frame in range(180):
                pose = rig.update(
                    1 / 50,
                    vx=1400 if frame % 2 else -1400,
                    vy=800,
                    mode=mode,
                    now=frame / 50,
                    walk_gait=frame * 0.3,
                    direction=1,
                    climb_side=1,
                )
                for value in (
                    pose.body_angle,
                    pose.head_tilt,
                    pose.arm_left,
                    pose.arm_right,
                    pose.leg_left,
                    pose.leg_right,
                ):
                    self.assertTrue(math.isfinite(value))
                    self.assertLessEqual(abs(value), 40.0, mode)
                self.assertGreaterEqual(pose.scale_y, 0.8)
                self.assertLessEqual(pose.scale_y, 1.15)


if __name__ == "__main__":
    unittest.main()
