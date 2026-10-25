"""Small drawing toolkit used by the placeholder-art generator.

The art is drawn in a 360 x 540 "design space".  We render at 4x and
downsample to 2x, which gives clean edges on high-DPI displays without
requiring any external illustration tool.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw

DESIGN_W = 360
DESIGN_H = 540
SS = 4                 # supersampling factor
OUT_SCALE = 2          # exported pixels per design pixel

OUTLINE = (57, 47, 58, 255)
INK = (48, 39, 51, 255)
CREAM = (255, 252, 245, 255)
MOUTH = (157, 73, 83, 255)
TONGUE = (255, 139, 151, 255)
BLUSH = (255, 164, 157, 255)
SHADOW = (64, 48, 66, 80)


def sc(value: float) -> int:
    return int(round(value * SS))


def canvas(w: float = DESIGN_W, h: float = DESIGN_H) -> Image.Image:
    return Image.new("RGBA", (sc(w), sc(h)), (0, 0, 0, 0))


def _box(values: Sequence[float]) -> list[int]:
    return [sc(v) for v in values]


def _pts(values: Iterable[tuple[float, float]]) -> list[tuple[int, int]]:
    return [(sc(x), sc(y)) for x, y in values]


def bezier(points: Sequence[tuple[float, float]], steps: int = 28) -> list[tuple[float, float]]:
    """Evaluate a cubic (or chained cubic) Bezier path."""

    if len(points) < 4:
        return list(points)
    result: list[tuple[float, float]] = []
    for i in range(0, len(points) - 3, 3):
        p0, p1, p2, p3 = points[i : i + 4]
        for n in range(steps):
            t = n / steps
            u = 1 - t
            x = u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0]
            y = u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]
            result.append((x, y))
    result.append(points[-1])
    return result


class Art:
    """Thin wrapper around ImageDraw with design-space coordinates."""

    def __init__(self, image: Image.Image, outline: tuple[int, int, int, int] = OUTLINE):
        self.image = image
        self.draw = ImageDraw.Draw(image)
        self.outline = outline

    # -- primitives -----------------------------------------------------
    def ellipse(
        self,
        box: Sequence[float],
        fill,
        outline=None,
        width: float = 3.0,
    ) -> None:
        self.draw.ellipse(
            _box(box),
            fill=fill,
            outline=self.outline if outline is None and width > 0 else outline,
            width=sc(width) if width > 0 else 0,
        )

    def circle(self, cx: float, cy: float, r: float, fill, outline=None, width: float = 3.0) -> None:
        self.ellipse((cx - r, cy - r, cx + r, cy + r), fill, outline, width)

    def rounded(
        self,
        box: Sequence[float],
        radius: float,
        fill,
        outline=None,
        width: float = 3.0,
    ) -> None:
        self.draw.rounded_rectangle(
            _box(box),
            radius=sc(radius),
            fill=fill,
            outline=self.outline if outline is None and width > 0 else outline,
            width=sc(width) if width > 0 else 0,
        )

    def rectangle(self, box: Sequence[float], fill, outline=None, width: float = 0.0) -> None:
        self.draw.rectangle(
            _box(box),
            fill=fill,
            outline=self.outline if outline is None and width > 0 else outline,
            width=sc(width) if width > 0 else 0,
        )

    def polygon(
        self,
        points: Iterable[tuple[float, float]],
        fill,
        outline=None,
        width: float = 3.0,
    ) -> None:
        points = list(points)
        if len(points) < 3:
            return
        pts = _pts(points)
        self.draw.polygon(pts, fill=fill)
        if width > 0:
            col = self.outline if outline is None else outline
            self.draw.line(pts + [pts[0]], fill=col, width=sc(width), joint="curve")

    def line(
        self,
        points: Iterable[tuple[float, float]],
        fill,
        width: float,
        outline=None,
        outline_width: float = 0.0,
    ) -> None:
        points = list(points)
        if not points:
            return
        pts = _pts(points)
        if outline_width > 0:
            col = self.outline if outline is None else outline
            self.draw.line(pts, fill=col, width=sc(width + outline_width * 2), joint="curve")
            for x, y in pts:
                self.draw.ellipse(
                    (x - sc(width / 2 + outline_width), y - sc(width / 2 + outline_width),
                     x + sc(width / 2 + outline_width), y + sc(width / 2 + outline_width)),
                    fill=col,
                )
        self.draw.line(pts, fill=fill, width=sc(width), joint="curve")
        for x, y in pts:
            self.draw.ellipse(
                (x - sc(width / 2), y - sc(width / 2), x + sc(width / 2), y + sc(width / 2)),
                fill=fill,
            )

    def curve(
        self,
        points: Iterable[tuple[float, float]],
        fill,
        width: float,
        outline=None,
        outline_width: float = 0.0,
    ) -> None:
        self.line(points, fill, width, outline, outline_width)

    def arc(
        self,
        box: Sequence[float],
        start: float,
        end: float,
        fill,
        width: float,
    ) -> None:
        self.draw.arc(_box(box), start, end, fill=fill, width=sc(width))

    def pieslice(self, box: Sequence[float], start: float, end: float, fill, outline=None) -> None:
        self.draw.pieslice(
            _box(box),
            start,
            end,
            fill=fill,
            outline=self.outline if outline is None else outline,
            width=sc(2.6),
        )

    # -- composite helpers ---------------------------------------------
    def limb(
        self,
        points: Iterable[tuple[float, float]],
        width: float,
        fill,
        outline_width: float = 3.0,
    ) -> None:
        self.line(points, fill, width, self.outline, outline_width)

    def star(self, cx: float, cy: float, radius: float, fill, outline=None, points: int = 5) -> None:
        verts = []
        for i in range(points * 2):
            angle = -math.pi / 2 + i * math.pi / points
            r = radius if i % 2 == 0 else radius * 0.43
            verts.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
        self.polygon(verts, fill, outline)

    def heart(self, cx: float, cy: float, size: float, fill) -> None:
        pts = []
        for i in range(64):
            t = 2 * math.pi * i / 64
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
            pts.append((cx + x * size / 32, cy + y * size / 32 - size * 0.16))
        self.polygon(pts, fill, outline=None, width=0)

    def shimmer(self, cx: float, cy: float, r: float, fill) -> None:
        self.polygon(
            [
                (cx, cy - r),
                (cx + r * 0.22, cy - r * 0.22),
                (cx + r, cy),
                (cx + r * 0.22, cy + r * 0.22),
                (cx, cy + r),
                (cx - r * 0.22, cy + r * 0.22),
                (cx - r, cy),
                (cx - r * 0.22, cy - r * 0.22),
            ],
            fill,
            outline=None,
            width=0,
        )


def save_layer(image: Image.Image, path: Path, size: tuple[int, int] = (DESIGN_W, DESIGN_H)) -> None:
    """Downsample a 4x working image to the 2x export size."""

    path.parent.mkdir(parents=True, exist_ok=True)
    out = image.resize((size[0] * OUT_SCALE, size[1] * OUT_SCALE), Image.Resampling.LANCZOS)
    out.save(path, "PNG", optimize=True)


def save_icon(image: Image.Image, path: Path, size: int = 512) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    side = max(image.width, image.height)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(image, ((side - image.width) // 2, (side - image.height) // 2))
    square.resize((size, size), Image.Resampling.LANCZOS).save(path, "PNG", optimize=True)


def alpha_bbox(path: Path, pad: int = 8) -> tuple[int, int, int, int]:
    image = Image.open(path).convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if not bbox:
        return (0, 0, image.width, image.height)
    x0, y0, x1, y1 = bbox
    return (
        max(0, x0 - pad),
        max(0, y0 - pad),
        min(image.width, x1 + pad),
        min(image.height, y1 + pad),
    )
