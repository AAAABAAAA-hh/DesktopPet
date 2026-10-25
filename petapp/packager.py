"""Generic one-image character packager for Deskling.

This is the single production pipeline behind **every** character, including the
bundled Elaina and the “➕ 导入新角色” button:

1. load any local image (PNG / JPEG / WEBP / animated first frame, EXIF aware);
2. keep an existing alpha channel, or key out a flat background with a
   border-connected flood fill; busy photos fall back to a clean paper sticker;
3. fit the subject onto the shared 720×1080 transparent export canvas, bottom
   aligned;
4. analyse the silhouette to find the neck, then emit aligned ``head.png`` and
   ``body.png`` layers plus ``body_full.png``;
5. keep the original face untouched: no synthetic eyes, blush or mouth are
   ever painted onto the head layer; only manually supplied expression files
   are used;
6. extract a normalized 2D outline / Root → Torso → Neck → Head skeleton and
   a small skin mesh for Godot-style 2D pipelines;
7. write a complete, self-contained ``config.json`` with click boxes, the neck
   pivot, pose metadata and a per-character motion profile.

The module uses only ``PyQt6`` (already required by the app), so importing a
character does not add a Pillow/NumPy dependency to the runtime.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QImageReader, QPainter, QPainterPath, QPen

from . import vision
from .config import CharacterConfig, load_character
from .motion import MotionProfile
from .skeleton import build_skeleton
from .sockets import default_mount_points

log = logging.getLogger(__name__)

CANVAS_W = 360
CANVAS_H = 540
EXPORT_DPR = 2
EXPORT_W = CANVAS_W * EXPORT_DPR
EXPORT_H = CANVAS_H * EXPORT_DPR
DEFAULT_ACCENT = "#9B7BD6"
INK = QColor(57, 47, 58)
PAPER = QColor(255, 252, 243)

#: Largest working copy used by the keying pass.
SAMPLE_EDGE = 1100
#: How far a border pixel may stray from the detected background colour.
BG_TOLERANCE = 40
#: Fraction of border samples that must agree before flood fill is attempted.
BG_MIN_BORDER_MATCH = 0.46

# Canvas placement, shared by every character.
FIT_WIDTH = 0.92
FIT_HEIGHT = 0.94
BOTTOM_GAP = 0.014


@dataclass(frozen=True)
class LayerGeometry:
    """The measured skeleton used by all generated character configs."""

    neck_x: int
    neck_y: int
    mouth: tuple[float, float]
    pivot: tuple[float, float]


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def package_character(
    source: Path | str,
    characters_dir: Path | str,
    *,
    existing_slugs: set[str] | None = None,
    existing_names: set[str] | None = None,
    order: float = 0.0,
    name: str | None = None,
    slug: str | None = None,
    subtitle: str = "自定义导入角色",
    scale: float = 0.8,
    temper: float = 1.0,
    accent: str | None = None,
    motion: Mapping[str, Any] | None = None,
    rage_threshold: float = 99.5,
    generate_expressions: bool = True,
    bust_mode: bool | None = None,
    posture: str | None = None,
    big_head: bool | None = None,
    head_scale: float = 1.4,
    ai_cutout: bool | None = None,
) -> CharacterConfig:
    """Build a complete layered character folder and return its config.

    ``existing_slugs`` / ``existing_names`` keep imports from colliding.
    ``motion`` accepts the same nested mapping documented by
    :class:`petapp.motion.MotionProfile`; omitted values use safe defaults.

    ``posture`` is the settings-dialog choice: ``"stand"`` lets a tall sprite
    walk around, while ``"sit"`` (坐姿趴桌) pins it in place by setting
    ``bust_mode``.  ``bust_mode`` is the lower-level override used by tests and
    tools; an explicit value wins over automatic sticker detection.

    ``big_head`` is a tri-state option for tall/full-body or real-photo art:
    ``None`` auto-detects (photo sticker, very tall subject, or tiny head),
    ``True`` forces the 1.4x bobble-head composition, and ``False`` keeps the
    original proportions.  ``head_scale`` is the enlargement factor (1.1–2.0).

    ``ai_cutout`` is a tri-state option for background removal: ``None`` uses
    local rembg or OpenCV GrabCut when installed, ``True`` tries those optional
    paths and falls back locally when unavailable, ``False`` always uses the
    bundled flood-fill/sticker path.  No network access is performed here.
    """

    source = Path(source)
    characters_dir = Path(characters_dir)
    if not source.is_file():
        raise ValueError(f"找不到图片：{source}")
    image = load_photo(source)
    if image.width() < 16 or image.height() < 16:
        raise ValueError("这张图片太小了，换一张大一点的立绘或照片吧。")

    # AI cutout is active whenever the optional deps are present; with deps
    # installed a real photo never falls back to a paper sticker.  When the
    # deps are absent we keep the legacy local path so the app still starts.
    if ai_cutout is None:
        use_ai_cutout = vision.rembg_available() or vision.opencv_available()
    else:
        use_ai_cutout = bool(ai_cutout)
    cutout, sticker_mode, cutout_method = _prepare_subject(image, use_ai_cutout)
    canvas, content = _place_on_canvas(cutout)
    geometry = _measure_layers(canvas)
    head_layer, body_layer = _slice_layers(canvas, geometry)

    body_bbox = _alpha_bbox(body_layer)
    head_bbox = _alpha_bbox(head_layer)
    if body_bbox.isEmpty() or head_bbox.isEmpty():
        raise ValueError("无法从这张图片中切出头部和身体，请换一张主体更清晰的图片。")

    factor = max(1.0, min(2.0, float(head_scale)))
    # Use the source image's aspect rather than the cropped silhouette bbox:
    # a normal 3:4 anime doll has transparent side margins that make the bbox
    # look much taller than the drawing.  Real 9:16 photos and busy-background
    # stickers still auto-enable the bobble-head composition.
    aspect = image.height() / max(1.0, image.width())
    head_ratio = head_bbox.height() / max(1.0, content.height())
    auto_big_head = sticker_mode or aspect >= 1.65 or head_ratio < 0.18
    use_big_head = auto_big_head if big_head is None else bool(big_head)
    if use_big_head and factor > 1.001:
        canvas, head_layer, body_layer, geometry, head_bbox, body_bbox = _enlarge_head(
            canvas,
            head_layer,
            body_layer,
            geometry,
            factor,
        )
    else:
        use_big_head = False

    skeleton = _skeleton_document(canvas, head_bbox, body_bbox, geometry)
    avatar = _avatar_image(canvas, head_bbox)

    # No synthetic expressions: an imported single image has exactly its
    # original, clean head texture.  ``generate_expressions`` is kept as a
    # deprecated compatibility argument but is intentionally a no-op.
    _ = generate_expressions

    if name is None:
        resolved_name = _display_name(source.stem)
    else:
        resolved_name = str(name).strip()
        if not resolved_name:
            raise ValueError("角色名称不能为空，请填写一个名字。")
    if not resolved_name:
        resolved_name = "新同学"
    resolved_name = resolved_name[:24]
    existing_names = set(existing_names or ())
    name_collision = resolved_name in existing_names
    if name_collision:
        resolved_name = _unique_name(resolved_name, existing_names)
    # A repeated display name must also get an opaque id rather than a
    # name+number folder, so two imports can never look like the same
    # character on disk.  Distinct names keep their readable slug.
    slug_seed = slug if slug else ("" if name_collision else resolved_name)
    resolved_slug = _unique_slug(
        slug_seed,
        set(existing_slugs or ()),
        characters_dir,
    )
    palette = _accent_colour(canvas) if accent is None else _safe_accent(accent)

    head_rect = _normalise_rect(head_bbox, EXPORT_W, EXPORT_H)
    body_rect = _normalise_rect(body_bbox, EXPORT_W, EXPORT_H)
    tall_enough_to_walk = (
        not sticker_mode
        and content.height() / max(1.0, content.width()) >= 1.18
    )
    posture_key = str(posture or "").strip().lower()
    seated = posture_key in {"sit", "sitting", "desk", "坐姿", "坐姿趴桌", "趴桌"}
    if bust_mode is None:
        # A seated/desk portrait stays put; otherwise let tall art walk and
        # keep the paper-sticker fallback anchored.
        bust = seated or sticker_mode or not tall_enough_to_walk
    else:
        bust = bool(bust_mode)

    profile = MotionProfile.from_mapping(motion or {})
    resolved_subtitle = str(subtitle or "").strip() or "自定义导入角色"
    config: dict[str, Any] = {
        "name": resolved_name,
        "slug": resolved_slug,
        "subtitle": resolved_subtitle[:60],
        "order": round(float(order) + 1.0, 3),
        "scale": max(0.5, min(1.35, float(scale))),
        "temper": max(0.2, min(2.5, float(temper))),
        "accent": palette,
        "canvas": [CANVAS_W, CANVAS_H],
        "head_rect": [round(v, 4) for v in head_rect],
        "body_rect": [round(v, 4) for v in body_rect],
        "mouth": [round(v, 4) for v in geometry.mouth],
        "mount_points": {
            name: point.to_mapping()
            for name, point in default_mount_points(
                head_rect,
                body_rect,
                (float(geometry.mouth[0]), float(geometry.mouth[1])),
            ).items()
        },
        "bust_mode": bool(bust),
        "posture": "sit" if bust else "stand",
        "system": False,
        "big_head": bool(use_big_head),
        "head_scale": round(factor if use_big_head else 1.0, 3),
        "cutout": cutout_method,
        "avatar": "avatar.png",
        "poses": {
            "idle": "body.png",
            "sit": "body.png",
            "walk_left": "body.png",
            "walk_right": "body.png",
            "drag": "body.png",
        },
        "layers": {
            "body": "body.png",
            "walk": "body.png",
            "dangle": "body.png",
        },
        "expressions": {"normal": "head.png"},
        "skeleton": "skeleton.json",
        "parts": {},
        "rig": {"pivots": {"head": [round(v, 4) for v in geometry.pivot]}},
        "motion": profile.to_mapping(),
        "rage_threshold": max(1.0, min(100.0, float(rage_threshold))),
        "notes": (
            "由通用角色打包器生成：body_full.png 为整张透明立绘，"
            "head.png / body.png 共用 720x1080 画布；原图脸部不做任何重绘；"
            "skeleton.json 为标准 2D 骨骼/蒙皮网格配置。"
        ),
    }

    folder = characters_dir / resolved_slug
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError("角色文件夹已经存在，请换一张图片或先改名。") from exc
    try:
        if not canvas.save(str(folder / "body_full.png"), "PNG"):
            raise ValueError("保存角色图片失败，请检查 characters 文件夹是否可写。")
        if not head_layer.save(str(folder / "head.png"), "PNG"):
            raise ValueError("保存头部图层失败。")
        if not body_layer.save(str(folder / "body.png"), "PNG"):
            raise ValueError("保存身体图层失败。")
        if not avatar.save(str(folder / "avatar.png"), "PNG"):
            raise ValueError("保存头像失败。")
        (folder / "skeleton.json").write_text(
            json.dumps(skeleton, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (folder / "config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        # Never leave a half-written character behind to be picked up by the
        # character scanner on the next start.
        import shutil

        shutil.rmtree(folder, ignore_errors=True)
        raise
    return load_character(folder)


# Backwards-compatible name used by the settings dialog and existing tests.
def create_character(*args: Any, **kwargs: Any) -> CharacterConfig:
    return package_character(*args, **kwargs)


def load_photo(path: Path | str) -> QImage:
    """Read any supported local image, honouring EXIF orientation."""

    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise ValueError(f"无法读取图片：{reader.errorString() or path}")
    return image.convertToFormat(QImage.Format.Format_ARGB32)


# ---------------------------------------------------------------------------
# background removal
# ---------------------------------------------------------------------------


def _prepare_subject(
    image: QImage,
    use_ai_cutout: bool = False,
) -> tuple[QImage, bool, str]:
    """Return ``(transparent_subject, sticker_mode, cutout_method)``.

    Order: existing alpha → local rembg/u2net (when installed) → OpenCV
    GrabCut for complex borders → border flood fill → paper-sticker fallback.
    Nothing here touches the network; rembg only runs if its local Python
    package/model cache is present.
    """

    if _has_real_transparency(image):
        return _crop_alpha(_to_rgba(image)), False, "alpha"

    work = _scaled_for_work(image)
    rgba = _to_rgba(work)
    background, match = _background_colour(rgba)

    if use_ai_cutout:
        ai_cutout = vision.remove_background(image)
        if ai_cutout is not None:
            cropped = _crop_alpha(_to_rgba(ai_cutout))
            if cropped.width() >= 8 and cropped.height() >= 8:
                return cropped, False, "rembg"
        # rembg unavailable/failed: GrabCut handles the photo's door frame /
        # wall instead of falling back to a rectangular paper sticker.
        grabcut = vision.grabcut_foreground(image)
        if grabcut is not None:
            cropped = _crop_alpha(_to_rgba(grabcut))
            if cropped.width() >= 8 and cropped.height() >= 8:
                return cropped, False, "grabcut"
        raise ValueError(
            "无法去除照片背景：rembg 与 OpenCV GrabCut 均不可用。"
            "请执行 `pip install rembg onnxruntime opencv-python-headless` 后重试。"
        )

    if background is None or match < BG_MIN_BORDER_MATCH:
        return _sticker(image), True, "sticker"

    cutout = _flood_remove(rgba, background)
    if cutout is None:
        return _sticker(image), True, "sticker"
    cropped = _crop_alpha(cutout)
    if cropped.width() < 8 or cropped.height() < 8:
        return _sticker(image), True, "sticker"
    if _corners_still_opaque(cropped):
        # A gradient / patterned background only partly matched the key colour.
        return _sticker(image), True, "sticker"
    return cropped, False, "flood-fill"


def _corners_still_opaque(image: QImage) -> bool:
    """Detect a background that survived keying around the subject."""

    rgba = _to_rgba(image)
    width, height = rgba.width(), rgba.height()
    stride = rgba.bytesPerLine()
    data = bytes(rgba.constBits().asstring(rgba.sizeInBytes()))
    patch = max(3, min(width, height) // 18)
    corners = (
        (0, 0),
        (width - patch, 0),
        (0, height - patch),
        (width - patch, height - patch),
    )
    opaque_corners = 0
    for start_x, start_y in corners:
        opaque = 0
        total = 0
        for y in range(start_y, min(height, start_y + patch)):
            row = y * stride
            for x in range(start_x, min(width, start_x + patch)):
                total += 1
                if data[row + x * 4 + 3] > 40:
                    opaque += 1
        if total and opaque / total > 0.4:
            opaque_corners += 1
    return opaque_corners >= 2


def _to_rgba(image: QImage) -> QImage:
    return image.convertToFormat(QImage.Format.Format_RGBA8888)


def _scaled_for_work(image: QImage) -> QImage:
    longest = max(image.width(), image.height())
    if longest <= SAMPLE_EDGE:
        return image
    scale = SAMPLE_EDGE / float(longest)
    return image.scaled(
        max(16, round(image.width() * scale)),
        max(16, round(image.height() * scale)),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _has_real_transparency(image: QImage) -> bool:
    rgba = _to_rgba(image)
    width, height = rgba.width(), rgba.height()
    step_x = max(1, width // 90)
    step_y = max(1, height // 90)
    transparent = 0
    samples = 0
    stride = rgba.bytesPerLine()
    data = bytes(rgba.constBits().asstring(rgba.sizeInBytes()))
    for y in range(0, height, step_y):
        row = y * stride
        for x in range(0, width, step_x):
            samples += 1
            if data[row + x * 4 + 3] < 245:
                transparent += 1
    return samples > 0 and transparent / samples > 0.015


def _background_colour(rgba: QImage) -> tuple[tuple[int, int, int] | None, float]:
    """Most common border colour plus the fraction of border pixels matching it."""

    width, height = rgba.width(), rgba.height()
    stride = rgba.bytesPerLine()
    data = bytes(rgba.constBits().asstring(rgba.sizeInBytes()))
    step_x = max(1, width // 90)
    step_y = max(1, height // 90)
    samples: list[bytes] = []
    for x in range(0, width, step_x):
        for y in (0, height - 1):
            offset = y * stride + x * 4
            samples.append(data[offset : offset + 3])
    for y in range(0, height, step_y):
        for x in (0, width - 1):
            offset = y * stride + x * 4
            samples.append(data[offset : offset + 3])
    if not samples:
        return None, 0.0
    quantised = Counter(((c[0] // 24, c[1] // 24, c[2] // 24) for c in samples))
    bucket, count = quantised.most_common(1)[0]
    if count / len(samples) < BG_MIN_BORDER_MATCH:
        return None, count / len(samples)
    cluster = [
        c
        for c in samples
        if (c[0] // 24, c[1] // 24, c[2] // 24) == bucket
        and _distance(c[0], c[1], c[2], *bucket_centre(bucket)) <= 58
    ]
    if not cluster:
        return None, 0.0
    red = sum(c[0] for c in cluster) / len(cluster)
    green = sum(c[1] for c in cluster) / len(cluster)
    blue = sum(c[2] for c in cluster) / len(cluster)
    return (round(red), round(green), round(blue)), len(cluster) / len(samples)


def bucket_centre(bucket: tuple[int, int, int]) -> tuple[int, int, int]:
    return (bucket[0] * 24 + 12, bucket[1] * 24 + 12, bucket[2] * 24 + 12)


def _distance(r1: int, g1: int, b1: int, r2: int, g2: int, b2: int) -> float:
    return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5


def _flood_remove(rgba: QImage, background: tuple[int, int, int]) -> QImage | None:
    """Remove background pixels connected to the image border."""

    width, height = rgba.width(), rgba.height()
    stride = rgba.bytesPerLine()
    data = bytearray(rgba.constBits().asstring(rgba.sizeInBytes()))
    bg_r, bg_g, bg_b = background
    tolerance = BG_TOLERANCE
    removed = bytearray(width * height)
    stack: list[int] = []

    def matches(offset: int) -> bool:
        return _distance(
            data[offset], data[offset + 1], data[offset + 2], bg_r, bg_g, bg_b
        ) <= tolerance

    def push(x: int, y: int) -> None:
        index = y * width + x
        if removed[index]:
            return
        offset = y * stride + x * 4
        if matches(offset):
            removed[index] = 1
            data[offset + 3] = 0
            stack.append(index)

    for x in range(width):
        push(x, 0)
        push(x, height - 1)
    for y in range(height):
        push(0, y)
        push(width - 1, y)

    while stack:
        index = stack.pop()
        x = index % width
        y = index // width
        if x > 0:
            neighbour = index - 1
            if not removed[neighbour]:
                offset = y * stride + (x - 1) * 4
                if matches(offset):
                    removed[neighbour] = 1
                    data[offset + 3] = 0
                    stack.append(neighbour)
        if x + 1 < width:
            neighbour = index + 1
            if not removed[neighbour]:
                offset = y * stride + (x + 1) * 4
                if matches(offset):
                    removed[neighbour] = 1
                    data[offset + 3] = 0
                    stack.append(neighbour)
        if y > 0:
            neighbour = index - width
            if not removed[neighbour]:
                offset = (y - 1) * stride + x * 4
                if matches(offset):
                    removed[neighbour] = 1
                    data[offset + 3] = 0
                    stack.append(neighbour)
        if y + 1 < height:
            neighbour = index + width
            if not removed[neighbour]:
                offset = (y + 1) * stride + x * 4
                if matches(offset):
                    removed[neighbour] = 1
                    data[offset + 3] = 0
                    stack.append(neighbour)

    removed_count = sum(removed)
    total = max(1, width * height)
    if removed_count / total < 0.03:
        return None

    # Anti-halo pass: drop the one-pixel ring of background-coloured pixels
    # next to the removed area, otherwise keyed art gets a pale outline.
    tight = tolerance * 0.72
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if removed[index]:
                continue
            offset = y * stride + x * 4
            if data[offset + 3] == 0:
                continue
            if (
                _distance(data[offset], data[offset + 1], data[offset + 2], bg_r, bg_g, bg_b)
                > tight
            ):
                continue
            if (
                (x > 0 and removed[index - 1])
                or (x + 1 < width and removed[index + 1])
                or (y > 0 and removed[index - width])
                or (y + 1 < height and removed[index + width])
            ):
                data[offset + 3] = 0

    foreground = sum(1 for i in range(0, len(data), 4) if data[i + 3] > 16)
    if foreground / total < 0.02:
        return None
    return QImage(bytes(data), width, height, stride, QImage.Format.Format_RGBA8888).copy()


def _crop_alpha(image: QImage) -> QImage:
    bbox = _alpha_bbox(image)
    if bbox.isEmpty():
        return image
    return _to_rgba(image).copy(bbox)


def _sticker(image: QImage) -> QImage:
    """A paper photo-cutout fallback for images with a busy background."""

    source = image
    longest = max(source.width(), source.height())
    if longest > 1400:
        scale = 1400 / float(longest)
        source = source.scaled(
            round(source.width() * scale),
            round(source.height() * scale),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    width, height = source.width(), source.height()
    pad = max(10, round(max(width, height) * 0.04))
    border = max(5, round(min(width, height) * 0.014))
    out = QImage(
        width + pad * 2,
        height + pad * 2,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHints(
        QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
    )
    rect = QRectF(pad, pad, width, height)
    radius = max(10.0, min(width, height) * 0.075)
    paper_rect = rect.adjusted(-pad * 0.42, -pad * 0.42, pad * 0.42, pad * 0.42)
    painter.setPen(QPen(INK, border * 1.2))
    painter.setBrush(PAPER)
    painter.drawRoundedRect(paper_rect, radius, radius)
    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    painter.save()
    painter.setClipPath(clip)
    painter.drawImage(rect, source, QRectF(source.rect()))
    painter.restore()
    painter.setPen(QPen(INK, border))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
    painter.end()
    return out


# ---------------------------------------------------------------------------
# canvas staging + silhouette analysis
# ---------------------------------------------------------------------------


def _place_on_canvas(subject: QImage) -> tuple[QImage, QRect]:
    """Fit the subject onto the 720x1080 export canvas, bottom aligned."""

    canvas = QImage(EXPORT_W, EXPORT_H, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    source_w = max(1, subject.width())
    source_h = max(1, subject.height())
    scale = min(
        (EXPORT_W * FIT_WIDTH) / source_w,
        (EXPORT_H * FIT_HEIGHT) / source_h,
    )
    draw_w = max(1, round(source_w * scale))
    draw_h = max(1, round(source_h * scale))
    left = (EXPORT_W - draw_w) // 2
    bottom_margin = round(EXPORT_H * BOTTOM_GAP)
    top = EXPORT_H - bottom_margin - draw_h
    if top < 0:
        top = 0
        draw_h = EXPORT_H
    painter = QPainter(canvas)
    painter.setRenderHints(
        QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing
    )
    painter.drawImage(QRectF(left, top, draw_w, draw_h), subject, QRectF(subject.rect()))
    painter.end()
    content = QRect(left, top, draw_w, draw_h)
    bbox = _alpha_bbox(canvas)
    return canvas, bbox if not bbox.isEmpty() else content


def _avatar_image(canvas: QImage, head_bbox: QRect, size: int = 256) -> QImage:
    """Square, face-centred card avatar.

    OpenCV's Haar cascade is used when available; without it, the fallback is
    the upper-middle of the head silhouette (not the top-left background).
    """

    face = vision.detect_face_box(canvas, head_bbox)
    box = vision.face_centred_box(
        head_bbox,
        face,
        (canvas.width(), canvas.height()),
    )
    cropped = canvas.copy(box)
    return cropped.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _skeleton_document(
    canvas: QImage,
    head_bbox: QRect,
    body_bbox: QRect,
    geometry: LayerGeometry,
) -> dict:
    """Build the normalized skeleton/mesh document for the final canvas."""

    rgba = _to_rgba(canvas)
    width, height = rgba.width(), rgba.height()
    stride = rgba.bytesPerLine()
    data = bytes(rgba.constBits().asstring(rgba.sizeInBytes()))

    def alpha_at(x: int, y: int) -> int:
        x = max(0, min(width - 1, int(x)))
        y = max(0, min(height - 1, int(y)))
        return data[y * stride + x * 4 + 3]

    return build_skeleton(
        canvas=(width, height),
        head_bbox=(head_bbox.left(), head_bbox.top(), head_bbox.width(), head_bbox.height()),
        body_bbox=(body_bbox.left(), body_bbox.top(), body_bbox.width(), body_bbox.height()),
        neck=geometry.pivot,
        alpha_at=alpha_at,
    )


def _alpha_bbox(image: QImage) -> QRect:
    rgba = _to_rgba(image)
    width, height = rgba.width(), rgba.height()
    stride = rgba.bytesPerLine()
    data = bytes(rgba.constBits().asstring(rgba.sizeInBytes()))
    left, top, right, bottom = width, height, -1, -1
    for y in range(height):
        row = y * stride
        for x in range(width):
            if data[row + x * 4 + 3] > 16:
                if x < left:
                    left = x
                if x > right:
                    right = x
                if y < top:
                    top = y
                if y > bottom:
                    bottom = y
    if right < left or bottom < top:
        return QRect()
    return QRect(left, top, right - left + 1, bottom - top + 1)


def _row_alpha_widths(image: QImage) -> tuple[list[int], bytes, int]:
    rgba = _to_rgba(image)
    width, height = rgba.width(), rgba.height()
    stride = rgba.bytesPerLine()
    data = bytes(rgba.constBits().asstring(rgba.sizeInBytes()))
    widths = [0] * height
    for y in range(height):
        row = y * stride
        count = 0
        for x in range(0, width, 2):
            if data[row + x * 4 + 3] > 16:
                count += 1
        widths[y] = count * 2
    return widths, data, stride


def _measure_layers(canvas: QImage) -> LayerGeometry:
    """Find the neck and derive the click boxes / pivot from the silhouette."""

    bbox = _alpha_bbox(canvas)
    if bbox.isEmpty():
        raise ValueError("图片主体是空的，无法分析角色。")
    fig_top, fig_bottom = bbox.top(), bbox.bottom()
    fig_h = max(1, bbox.height())
    widths, data, stride = _row_alpha_widths(canvas)
    window = max(3, int(fig_h * 0.012))
    half = window // 2

    def smooth(index: int) -> int:
        start = max(fig_top, index - half)
        end = min(fig_bottom, index + half)
        return sum(widths[start : end + 1]) // max(1, end - start + 1)

    head_limit = min(fig_bottom, fig_top + int(fig_h * 0.48))
    peak = max(range(fig_top, max(fig_top + 1, head_limit)), key=lambda y: smooth(y))
    peak_width = max(1, smooth(peak))
    search_start = min(fig_bottom, peak + max(4, int(fig_h * 0.03)))
    search_end = min(
        fig_bottom - 4,
        peak + max(12, int(fig_h * 0.30)),
        fig_top + int(fig_h * 0.72),
    )
    neck_y = 0
    if search_end > search_start:
        candidate = min(range(search_start, search_end), key=lambda y: smooth(y))
        candidate_width = smooth(candidate)
        if candidate_width <= peak_width * 0.55:
            neck_y = candidate
    if neck_y <= 0:
        aspect = bbox.width() / fig_h
        if aspect > 0.72:
            ratio = 0.50  # chibi / hat characters: neck sits at mid-figure
        elif aspect > 0.55:
            ratio = 0.36
        elif aspect > 0.42:
            ratio = 0.30
        else:
            ratio = 0.22
        neck_y = fig_top + int(round(fig_h * ratio))
    neck_y = max(fig_top + int(fig_h * 0.12), min(fig_bottom - int(fig_h * 0.04), neck_y))

    # Neck x: median of opaque pixels in a thin band; stable even with hair.
    xs: list[int] = []
    band_top = max(fig_top, neck_y - max(4, int(fig_h * 0.01)))
    band_bottom = min(fig_bottom + 1, neck_y + max(5, int(fig_h * 0.01)))
    width = canvas.width()
    for y in range(band_top, band_bottom):
        row = y * stride
        for x in range(width):
            if data[row + x * 4 + 3] > 24:
                xs.append(x)
    neck_x = int(sorted(xs)[len(xs) // 2]) if xs else (bbox.left() + bbox.right()) // 2

    # Mouth position is derived from the head silhouette rather than the neck:
    # a wide hat pulls the face down inside the head bbox, while a normal
    # anime head keeps the eyes near the middle of the hair+face bbox.
    head_h = max(1, neck_y - bbox.top())
    head_w = max(1, bbox.width())
    if head_w > head_h * 1.15:
        eye_y = bbox.top() + int(head_h * 0.77)
    else:
        eye_y = bbox.top() + int(head_h * 0.52)
    mouth_y = min(neck_y - 6, eye_y + int(head_h * 0.17))
    mouth = (
        round(neck_x / EXPORT_W, 4),
        round(max(0.02, mouth_y / EXPORT_H), 4),
    )
    pivot = (round(neck_x / EXPORT_W, 4), round(neck_y / EXPORT_H, 4))
    return LayerGeometry(
        neck_x=neck_x,
        neck_y=neck_y,
        mouth=mouth,
        pivot=pivot,
    )


def _slice_layers(canvas: QImage, geometry: LayerGeometry) -> tuple[QImage, QImage]:
    """Cut aligned head/body layers from the full canvas.

    ``body.png`` keeps a small under-lap above the neck so a rotating head never
    exposes a transparent seam.
    """

    bbox = _alpha_bbox(canvas)
    overlap = max(8, round(max(1, bbox.height()) * 0.025))
    head = _mask_rows(canvas, 0, geometry.neck_y)
    body = _mask_rows(canvas, max(0, geometry.neck_y - overlap), EXPORT_H)
    return head, body


def _enlarge_head(
    canvas: QImage,
    head: QImage,
    body: QImage,
    geometry: LayerGeometry,
    factor: float,
) -> tuple[QImage, QImage, QImage, LayerGeometry, QRect, QRect]:
    """Compose a bigger head over the same body ("bobble-head" portrait).

    The head content is cropped, scaled uniformly around the neck, then pasted
    back over the body.  The body layer is kept intact, while the mouth and
    click rectangle are remapped so expressions and hit-testing stay aligned
    with the enlarged face.
    """

    bbox = _alpha_bbox(head)
    if bbox.isEmpty():
        return canvas, head, body, geometry, bbox, _alpha_bbox(body)
    content = head.copy(bbox)
    target_w = max(1, round(content.width() * factor))
    target_h = max(1, round(content.height() * factor))
    scaled = content.scaled(
        target_w,
        target_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if scaled.width() > EXPORT_W or scaled.height() > EXPORT_H:
        scaled = scaled.scaled(
            EXPORT_W,
            EXPORT_H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    x = round(geometry.neck_x - scaled.width() / 2.0)
    y = round(geometry.neck_y - scaled.height())
    x = max(0, min(EXPORT_W - scaled.width(), x))
    y = max(0, min(EXPORT_H - scaled.height(), y))

    new_head = QImage(EXPORT_W, EXPORT_H, QImage.Format.Format_ARGB32_Premultiplied)
    new_head.fill(Qt.GlobalColor.transparent)
    head_painter = QPainter(new_head)
    head_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    head_painter.drawImage(x, y, scaled)
    head_painter.end()

    new_canvas = body.copy()
    body_painter = QPainter(new_canvas)
    body_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    body_painter.drawImage(x, y, scaled)
    body_painter.end()

    new_head_bbox = _alpha_bbox(new_head)
    new_body_bbox = _alpha_bbox(body)
    mouth_x = geometry.mouth[0] * EXPORT_W
    mouth_y = geometry.mouth[1] * EXPORT_H
    rel_x = (mouth_x - bbox.left()) / max(1.0, bbox.width())
    rel_y = (mouth_y - bbox.top()) / max(1.0, bbox.height())
    new_mouth = (
        max(0.0, min(1.0, (new_head_bbox.left() + rel_x * new_head_bbox.width()) / EXPORT_W)),
        max(0.0, min(1.0, (new_head_bbox.top() + rel_y * new_head_bbox.height()) / EXPORT_H)),
    )
    new_geometry = LayerGeometry(
        neck_x=geometry.neck_x,
        neck_y=geometry.neck_y,
        mouth=new_mouth,
        pivot=geometry.pivot,
    )
    return new_canvas, new_head, body, new_geometry, new_head_bbox, new_body_bbox


def _mask_rows(image: QImage, keep_top: int, keep_bottom: int) -> QImage:
    rgba = _to_rgba(image)
    width, height = rgba.width(), rgba.height()
    stride = rgba.bytesPerLine()
    data = bytearray(rgba.constBits().asstring(rgba.sizeInBytes()))
    for y in range(height):
        if keep_top <= y < keep_bottom:
            continue
        row = y * stride
        for x in range(width):
            data[row + x * 4 + 3] = 0
    return QImage(bytes(data), width, height, stride, QImage.Format.Format_RGBA8888).copy()


def _normalise_rect(
    rect: QRect, width: int, height: int
) -> tuple[float, float, float, float]:
    return (
        max(0.0, min(1.0, rect.left() / width)),
        max(0.0, min(1.0, rect.top() / height)),
        max(0.02, min(1.0, rect.width() / width)),
        max(0.02, min(1.0, rect.height() / height)),
    )


# ---------------------------------------------------------------------------
# naming and palette
# ---------------------------------------------------------------------------


def _display_name(stem: str) -> str:
    name = re.sub(r"[_\-.]+", " ", stem).strip()
    name = re.sub(r"\s+", " ", name)
    if not name or re.fullmatch(
        r"(?i)(img|dsc|dscn|photo|image|screenshot|微信图片)[ _-]*\d*", name
    ):
        return "新同学"
    return name[:16]


def _unique_name(name: str, existing: set[str]) -> str:
    index = 2
    while f"{name}{index}" in existing:
        index += 1
    return f"{name}{index}"


#: Filename-like defaults that must never become a shared character folder.
#: Importing two files named ``images`` used to be the classic collision case;
#: those now get an opaque ``char_NNN`` id instead.
_GENERIC_SLUGS = frozenset(
    {
        "image",
        "images",
        "img",
        "photo",
        "photos",
        "picture",
        "pictures",
        "screenshot",
        "screenshots",
        "custom",
        "character",
        "characters",
        "char",
        "new",
        "untitled",
        "deskling",
        "微信图片",
    }
)


def _unique_slug(name: str, existing: set[str], characters_dir: Path) -> str:
    """Allocate a collision-proof character folder id.

    A readable name-based slug is used when it is free and not a generic
    filename.  On any collision (or for ``images``-style names) a stable
    ``char_001``, ``char_002``... id is allocated, so another import can never
    reuse or overwrite an existing character directory.
    """

    base = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]+", "_", name).strip("_")
    generic = (
        not base
        or base.lower() in _GENERIC_SLUGS
        or bool(
            re.fullmatch(
                r"(?i)(img|image|dsc|dscn|photo|picture|screenshot|微信图片)[ _-]*\d*",
                base,
            )
        )
    )
    if not generic and base not in existing and not (characters_dir / base).exists():
        return base

    index = 1
    while True:
        candidate = f"char_{index:03d}"
        if candidate not in existing and not (characters_dir / candidate).exists():
            return candidate
        index += 1


def _safe_accent(value: str) -> str:
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return value
    return DEFAULT_ACCENT


def _accent_colour(image: QImage) -> str:
    rgba = _to_rgba(image)
    width, height = rgba.width(), rgba.height()
    stride = rgba.bytesPerLine()
    data = bytes(rgba.constBits().asstring(rgba.sizeInBytes()))
    step = max(1, min(width, height) // 72)
    colourful: list[tuple[int, int, int, int]] = []
    for y in range(0, height, step):
        row = y * stride
        for x in range(0, width, step):
            offset = row + x * 4
            if data[offset + 3] < 80:
                continue
            red, green, blue = data[offset], data[offset + 1], data[offset + 2]
            high = max(red, green, blue)
            low = min(red, green, blue)
            saturation = high - low
            if saturation < 22 or high < 45:
                continue
            colourful.append((saturation, red, green, blue))
    if not colourful:
        return DEFAULT_ACCENT
    colourful.sort(reverse=True)
    chosen = colourful[: max(1, len(colourful) // 8)]
    red = sum(c[1] for c in chosen) // len(chosen)
    green = sum(c[2] for c in chosen) // len(chosen)
    blue = sum(c[3] for c in chosen) // len(chosen)
    colour = QColor(red, green, blue)
    hue, saturation, value, _alpha = colour.getHsv()
    saturation = max(90, min(205, saturation))
    value = max(105, min(225, value))
    return QColor.fromHsv(hue, saturation, value).name()
