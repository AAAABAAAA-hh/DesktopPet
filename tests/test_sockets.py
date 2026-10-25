"""Pure-Python tests for the anchor/socket geometry."""

from __future__ import annotations

import unittest

from petapp.sockets import (
    MountPoint,
    default_mount_points,
    fit_for_width,
    mount_rect,
    normalise_mount_points,
    offset_for_center,
)

HEAD = (0.14, 0.025, 0.72, 0.46)
BODY = (0.15, 0.48, 0.70, 0.50)
MOUTH = (0.5, 0.4)
CANVAS = (360.0, 540.0)


class SocketTests(unittest.TestCase):
    def test_defaults_cover_the_expected_attachment_points(self) -> None:
        points = default_mount_points(HEAD, BODY, MOUTH)
        for name in ("head_top", "face", "mouth", "hand"):
            self.assertIn(name, points)
            self.assertGreater(points[name].width, 0.0)
        self.assertNotIn("torso", points, "躯干装扮锚点已彻底移除")
        self.assertNotIn("body", points, "躯干装扮锚点已彻底移除")
        self.assertAlmostEqual(points["mouth"].x, MOUTH[0])
        self.assertAlmostEqual(points["mouth"].y, MOUTH[1])

    def test_mount_rect_is_centred_and_scales_by_width(self) -> None:
        mount = MountPoint("test", 0.5, 0.5, 0.25)
        rect = mount_rect(mount, CANVAS, (100, 200), fit=2.0)
        left, top, width, height = rect
        self.assertAlmostEqual(width, 0.25 * 360 * 2.0)
        self.assertAlmostEqual(height, width * 2.0, msg="等比缩放，保持 PNG 比例")
        self.assertAlmostEqual(left + width / 2, 0.5 * 360)
        self.assertAlmostEqual(top + height / 2, 0.5 * 540)

    def test_offset_is_measured_in_socket_widths(self) -> None:
        mount = MountPoint("test", 0.5, 0.5, 0.2)
        base = mount_rect(mount, CANVAS, (100, 100))
        shifted = mount_rect(mount, CANVAS, (100, 100), offset=(0.5, -0.25))
        socket_px = 0.2 * 360
        self.assertAlmostEqual(shifted[0] - base[0], 0.5 * socket_px)
        self.assertAlmostEqual(shifted[1] - base[1], -0.25 * socket_px)

    def test_fit_and_offset_helpers_round_trip(self) -> None:
        mount = MountPoint("test", 0.4, 0.6, 0.2)
        fit = fit_for_width(mount, CANVAS, 72.0)
        self.assertAlmostEqual(fit, 1.0)
        center = (144.0, 300.0)
        offset = offset_for_center(mount, CANVAS, center)
        left, top, width, height = mount_rect(
            mount, CANVAS, (10, 10), fit=fit, offset=offset
        )
        self.assertAlmostEqual(left + width / 2, center[0])
        self.assertAlmostEqual(top + height / 2, center[1])

    def test_invalid_images_never_produce_nan(self) -> None:
        mount = MountPoint("test", 0.5, 0.5, 0.2)
        rect = mount_rect(mount, CANVAS, (0, 0), fit=1.0)
        self.assertTrue(all(value == value for value in rect))
        self.assertGreater(rect[2], 0.0)
        self.assertGreater(rect[3], 0.0)

    def test_normalise_allows_custom_sockets_and_short_form(self) -> None:
        defaults = default_mount_points(HEAD, BODY, MOUTH)
        points = normalise_mount_points(
            {
                "head_top": {"point": [0.4, 0.1], "width": 0.8},
                "hand": [0.3, 0.65],
                "tail": {"point": [0.9, 0.7], "width": 0.1},
                "torso": {"point": [0.5, 0.69], "width": 0.5},
            },
            defaults,
        )
        self.assertAlmostEqual(points["head_top"].x, 0.4)
        self.assertAlmostEqual(points["head_top"].width, 0.8)
        self.assertAlmostEqual(points["hand"].x, 0.3)
        self.assertAlmostEqual(points["hand"].width, defaults["hand"].width)
        self.assertIn("tail", points)
        self.assertAlmostEqual(points["tail"].width, 0.1)
        self.assertNotIn("torso", points, "旧配置里的 torso 锚点必须被忽略")


if __name__ == "__main__":
    unittest.main()
