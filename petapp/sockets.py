"""Anchor ("socket") geometry for accessories, food and prop sprites.

The pet is drawn on a normalised design canvas (usually 360 x 540).  A
character describes its attachment points in ``config.json``::

    "mount_points": {
      "head_top": {"point": [0.5, 0.14], "width": 0.71},
      "face":     {"point": [0.5, 0.31], "width": 0.62},
      "mouth":    {"point": [0.5, 0.40], "width": 0.18},
      "hand":     {"point": [0.5, 0.63], "width": 0.29}
    }

An external PNG sprite refers to one of those names and is scaled so that its
width is ``mount.width * fit`` of the canvas, then centred on the mount point.
``offset`` is expressed in mount-width units, so it scales together with the
sprite instead of drifting on characters of a different size.

**Accessories are deliberately limited** to three small sockets — ``head_top``,
``face`` and ``hand``.  The old ``torso`` / ``body`` overlay anchors were
removed together with the generic clothing layer: on a non-standard silhouette
a full-torso PNG can only show up as a misplaced rectangle.  Food still uses
``mouth``; the held book/tea lives on ``hand``.

This module is intentionally free of Qt and Pillow imports: the window, the
asset composer and the preview tooling all share exactly the same geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

#: Sockets that can carry a small accessory.  Anything else is not a wardrobe
#: slot any more.
ACCESSORY_SLOTS = ("head_top", "face", "hand")

#: Socket names understood by the bundled content.  Custom mount points are
#: allowed as well; these are only the ones with sensible geometric defaults.
DEFAULT_MOUNT_NAMES = ("head_top", "face", "mouth", "hand")

#: Legacy / deprecated anchors that must never be used for an overlay again.
LEGACY_MOUNT_NAMES = frozenset({"torso", "body"})

#: Fallback attachment per wardrobe slot.  A catalogue entry may override it
#: with its own ``"mount"`` key.  ``head`` is kept as a legacy alias for old
#: catalogues and is normalised to ``head_top``.
SLOT_MOUNTS = {
    "head": "head_top",
    "head_top": "head_top",
    "face": "face",
    "hand": "hand",
}

#: Where food and held props go unless the catalogue says otherwise.
DEFAULT_FOOD_MOUNT = "mouth"
DEFAULT_PROP_MOUNT = "hand"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalise_slot(value: Any, fallback: str = "") -> str:
    """Map a catalogue ``slot``/``mount`` value to a supported socket.

    ``head`` is accepted as the historical alias for ``head_top``.  Legacy
    ``outfit`` / ``torso`` / ``body`` values return an empty string so callers
    can skip those entries entirely instead of silently drawing a rectangle.
    """

    key = str(value or "").strip().lower()
    key = SLOT_MOUNTS.get(key, key)
    return key if key in ACCESSORY_SLOTS else fallback


def is_accessory_slot(value: Any) -> bool:
    return normalise_slot(value) in ACCESSORY_SLOTS


def resolve_mount_name(name: Any, available: Mapping[str, Any]) -> str:
    """Pick the best usable socket name for a requested anchor."""

    key = str(name or "").strip()
    if key in available:
        return key
    for fallback in ("face", "head_top", "hand", "mouth"):
        if fallback in available:
            return fallback
    return next(iter(available), "")


@dataclass(frozen=True)
class MountPoint:
    """One normalised attachment point on a character canvas."""

    name: str
    x: float
    y: float
    width: float

    def center(
        self, canvas: tuple[float, float]
    ) -> tuple[float, float]:
        """Return the anchor in design-space pixels."""

        return (self.x * canvas[0], self.y * canvas[1])

    def pixel_width(self, canvas: tuple[float, float]) -> float:
        return self.width * canvas[0]

    def to_mapping(self) -> dict[str, Any]:
        return {"point": [round(self.x, 6), round(self.y, 6)], "width": round(self.width, 6)}


def _as_float(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _as_point(value: Any, fallback: tuple[float, float]) -> tuple[float, float]:
    try:
        x, y = value
        point = (clamp(float(x), 0.0, 1.0), clamp(float(y), 0.0, 1.0))
    except (TypeError, ValueError):
        return fallback
    if not all(math.isfinite(v) for v in point):
        return fallback
    return point


def parse_mount_point(
    name: str,
    raw: Any,
    fallback: MountPoint,
) -> MountPoint:
    """Parse either ``{"point": [x, y], "width": w}`` or ``[x, y]``."""

    if isinstance(raw, Mapping):
        point = _as_point(
            raw.get("point", raw.get("pos", (fallback.x, fallback.y))),
            (fallback.x, fallback.y),
        )
        width = clamp(
            _as_float(raw.get("width"), fallback.width),
            0.01,
            2.0,
        )
    elif isinstance(raw, (list, tuple)):
        point = _as_point(raw, (fallback.x, fallback.y))
        width = fallback.width
    else:
        return fallback
    return MountPoint(name=name, x=point[0], y=point[1], width=width)


def default_mount_points(
    head_rect: tuple[float, float, float, float],
    body_rect: tuple[float, float, float, float],
    mouth: tuple[float, float],
) -> dict[str, MountPoint]:
    """Derive a usable socket set from the character hit rectangles.

    The values are intentionally generous: they are the socket's *reference*
    width, not the size of a particular hat.  Each catalogue entry fine-tunes
    the final size with its own ``fit`` multiplier.
    """

    hx, hy, hw, hh = head_rect
    bx, by, bw, bh = body_rect
    head_cx = hx + hw / 2.0
    body_cx = bx + bw / 2.0
    return {
        "head_top": MountPoint("head_top", head_cx, hy + hh * 0.25, hw * 0.98),
        "face": MountPoint("face", head_cx, hy + hh * 0.62, hw * 0.86),
        "mouth": MountPoint("mouth", mouth[0], mouth[1], max(0.12, hw * 0.25)),
        "hand": MountPoint("hand", body_cx, by + bh * 0.30, bw * 0.42),
    }


def normalise_mount_points(
    raw: Any,
    defaults: dict[str, MountPoint],
) -> dict[str, MountPoint]:
    """Merge a config's ``mount_points`` with the geometric defaults."""

    result = dict(defaults)
    if not isinstance(raw, Mapping):
        return result
    for name, value in raw.items():
        if not isinstance(name, str) or not name.strip():
            continue
        key = name.strip()
        if key.lower() in LEGACY_MOUNT_NAMES:
            # Old catalogue/config files may still contain clothing anchors.
            # Dropping them here guarantees they can never be mounted again.
            continue
        fallback = result.get(key)
        if fallback is None:
            # A custom socket without a default: centre it on the canvas.
            fallback = MountPoint(key, 0.5, 0.5, 0.25)
        result[key] = parse_mount_point(key, value, fallback)
    return result


def normalise_offset(value: Any, fallback: tuple[float, float] = (0.0, 0.0)) -> tuple[float, float]:
    """Offsets are stored in socket-width units and may be negative."""

    try:
        x, y = value
        offset = (clamp(float(x), -4.0, 4.0), clamp(float(y), -4.0, 4.0))
    except (TypeError, ValueError):
        return fallback
    if not all(math.isfinite(v) for v in offset):
        return fallback
    return offset


def mount_rect(
    mount: MountPoint,
    canvas: tuple[float, float],
    source_size: tuple[float, float],
    *,
    fit: float = 1.0,
    offset: tuple[float, float] = (0.0, 0.0),
    scale: float = 1.0,
) -> tuple[float, float, float, float]:
    """Return ``(left, top, width, height)`` in design-space pixels.

    The sprite is uniformly scaled by width, then centred on the mount point
    plus the optional offset.  A zero-sized source falls back to a square so a
    corrupt image can never produce NaNs in the painter transform.
    """

    source_w, source_h = float(source_size[0]), float(source_size[1])
    if source_w <= 0.0 or source_h <= 0.0:
        source_w, source_h = 1.0, 1.0
    socket_w = mount.pixel_width(canvas)
    width = max(0.1, socket_w * max(0.0, float(fit)) * max(0.0, float(scale)))
    height = width * source_h / source_w
    cx = mount.x * canvas[0] + float(offset[0]) * socket_w
    cy = mount.y * canvas[1] + float(offset[1]) * socket_w
    return (cx - width / 2.0, cy - height / 2.0, width, height)


def fit_for_width(
    mount: MountPoint,
    canvas: tuple[float, float],
    desired_width: float,
) -> float:
    """Inverse of :func:`mount_rect` width, used when migrating old art."""

    socket_w = mount.pixel_width(canvas)
    if socket_w <= 0.0:
        return 1.0
    return max(0.0, float(desired_width)) / socket_w


def offset_for_center(
    mount: MountPoint,
    canvas: tuple[float, float],
    center: tuple[float, float],
) -> tuple[float, float]:
    """Offset (socket-width units) that places a sprite centre on ``center``."""

    socket_w = mount.pixel_width(canvas)
    if socket_w <= 0.0:
        return (0.0, 0.0)
    return (
        (center[0] - mount.x * canvas[0]) / socket_w,
        (center[1] - mount.y * canvas[1]) / socket_w,
    )
