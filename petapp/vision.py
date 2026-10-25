"""Local vision helpers for real-photo AI background removal.

rembg + onnxruntime are now the primary cutout path.  The light ``silueta``
model is downloaded once by rembg itself (pooch) when the environment has
network; after that every import is fully local.  OpenCV remains the
face-detection and GrabCut fallback.
"""

from __future__ import annotations

import importlib.util
import io
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QBuffer, QIODevice, QRect
from PyQt6.QtGui import QImage

log = logging.getLogger(__name__)

#: Lightweight model used by default.  silueta keeps more facial detail than
#: u2netp on real portraits while remaining a small (44 MB) local model.
DEFAULT_REMBG_MODEL = "silueta"


@lru_cache(maxsize=1)
def rembg_available() -> bool:
    if os.environ.get("DESKLING_DISABLE_REMBG", "").strip() in {"1", "true", "yes"}:
        return False
    try:
        return (
            importlib.util.find_spec("rembg") is not None
            and importlib.util.find_spec("PIL") is not None
        )
    except Exception:
        return False


def _rembg_model_name() -> str:
    name = os.environ.get("DESKLING_REMBG_MODEL", "").strip()
    return name or DEFAULT_REMBG_MODEL


def _model_candidates() -> list[Path]:
    name = _rembg_model_name()
    home = Path.home()
    candidates = [
        home / ".rembg" / "models" / name / f"{name}.onnx",
        home / ".rembg" / "models" / "u2netp" / "u2netp.onnx",
        home / ".rembg" / "models" / "silueta" / "silueta.onnx",
        home / ".u2net" / "u2net.onnx",
    ]
    override = os.environ.get("REMBG_MODEL", "").strip()
    if override:
        candidates.insert(0, Path(override))
    return candidates


def rembg_model_path() -> Path | None:
    """Local model path, if it has already been downloaded."""

    for path in _model_candidates():
        if path.is_file():
            return path
    return None


def rembg_ready() -> bool:
    """True when the package is present and a model file is cached."""

    return rembg_available() and rembg_model_path() is not None


@lru_cache(maxsize=1)
def opencv_available() -> bool:
    if os.environ.get("DESKLING_DISABLE_OPENCV", "").strip() in {"1", "true", "yes"}:
        return False
    try:
        return (
            importlib.util.find_spec("cv2") is not None
            and importlib.util.find_spec("numpy") is not None
        )
    except Exception:
        return False


@lru_cache(maxsize=1)
def _rembg_session() -> Any | None:
    if not rembg_available():
        return None
    try:
        from rembg import new_session

        # This downloads the lightweight model once when it is absent.
        return new_session(_rembg_model_name())
    except Exception as exc:
        log.warning("rembg 会话创建失败：%s", exc)
        return None


def _qimage_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def _qimage_from_pil(image: Any) -> QImage:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    raw = rgba.tobytes("raw", "RGBA")
    return QImage(
        raw,
        width,
        height,
        width * 4,
        QImage.Format.Format_RGBA8888,
    ).copy()


def remove_background(image: QImage) -> QImage | None:
    """Run local rembg/silueta on a QImage, returning a clean alpha cutout.

    The lightweight model is downloaded automatically on the first call.
    Returns ``None`` only when rembg is unavailable or genuinely fails; the
    caller should then fall back to OpenCV GrabCut, not to a paper sticker.
    """

    if not rembg_available() or image.isNull():
        return None
    try:
        from PIL import Image
        from rembg import remove

        session = _rembg_session()
        if session is None:
            return None
        source = Image.open(io.BytesIO(_qimage_bytes(image)))
        output = remove(source, session=session)
        if output is None:
            return None
        cutout = _qimage_from_pil(output)
        if cutout.isNull():
            return None
        return cutout
    except Exception as exc:  # model missing / ONNX runtime error, …
        log.warning("rembg 抠图失败：%s", exc)
        return None


def grabcut_foreground(image: QImage) -> QImage | None:
    """OpenCV GrabCut fallback for complex real-photo backgrounds.

    Used only when rembg/u2net is unavailable.  The foreground rectangle is
    inset slightly from the border so door frames/walls are treated as
    background; the original RGB pixels are kept and only alpha is replaced.
    """

    if not opencv_available() or image.isNull():
        return None
    try:
        import cv2
        import numpy as np

        work = image
        longest = max(work.width(), work.height())
        if longest > 1100:
            scale = 1100.0 / longest
            work = work.scaled(
                max(16, round(work.width() * scale)),
                max(16, round(work.height() * scale)),
            )
        rgba = work.convertToFormat(QImage.Format.Format_RGBA8888)
        width, height = rgba.width(), rgba.height()
        stride = rgba.bytesPerLine()
        raw = bytes(rgba.constBits().asstring(rgba.sizeInBytes()))
        array = np.frombuffer(raw, dtype=np.uint8).reshape((height, stride))
        array = array[:, : width * 4].reshape((height, width, 4)).copy()
        rgb = cv2.cvtColor(array[:, :, :3], cv2.COLOR_RGB2BGR)
        mask = np.zeros((height, width), dtype=np.uint8)
        bgd = np.zeros((1, 65), dtype=np.float64)
        fgd = np.zeros((1, 65), dtype=np.float64)
        margin_x = max(2, int(width * 0.04))
        margin_y = max(2, int(height * 0.04))
        rect = (margin_x, margin_y, max(4, width - margin_x * 2), max(4, height - margin_y * 2))
        cv2.grabCut(rgb, mask, rect, bgd, fgd, 3, cv2.GC_INIT_WITH_RECT)
        keep = np.where(
            (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
        ).astype(np.uint8)
        coverage = float(np.count_nonzero(keep)) / float(width * height)
        if coverage < 0.04 or coverage > 0.985:
            return None
        # Feather the cutout edge slightly while keeping the original colour.
        keep = cv2.GaussianBlur(keep, (3, 3), 0)
        array[:, :, 3] = keep
        out = np.ascontiguousarray(array)
        return QImage(
            out.data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
    except Exception as exc:
        log.debug("OpenCV GrabCut 抠图失败：%s", exc)
        return None


def _qimage_rgb_array(image: QImage):
    import numpy as np

    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = rgba.width(), rgba.height()
    stride = rgba.bytesPerLine()
    data = bytes(rgba.constBits().asstring(rgba.sizeInBytes()))
    array = np.frombuffer(data, dtype=np.uint8).reshape((height, stride))
    array = array[:, : width * 4].reshape((height, width, 4))
    return np.ascontiguousarray(array[:, :, :3])


def detect_face_box(image: QImage, head_bbox: QRect | None = None) -> QRect | None:
    """Locate a face with OpenCV's Haar cascade, in image pixel coordinates."""

    if not opencv_available() or image.isNull():
        return None
    try:
        import cv2

        rgb = _qimage_rgb_array(image)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        cascade_path = os.path.join(
            cv2.data.haarcascades, "haarcascade_frontalface_default.xml"
        )
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            return None
        min_side = max(24, min(gray.shape[0], gray.shape[1]) // 12)
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(min_side, min_side),
        )
        if len(faces) == 0:
            return None
        candidates = [QRect(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]
        if head_bbox is not None and not head_bbox.isEmpty():
            in_head = [
                face
                for face in candidates
                if head_bbox.intersects(face)
                or head_bbox.contains(face.center())
            ]
            if in_head:
                candidates = in_head
        # Pick the largest detected face (closest subject).
        return max(candidates, key=lambda rect: rect.width() * rect.height())
    except Exception as exc:
        log.debug("OpenCV 人脸检测失败：%s", exc)
        return None


def face_centred_box(
    head_bbox: QRect,
    face_bbox: QRect | None,
    image_size: tuple[int, int],
    *,
    margin: float = 0.55,
) -> QRect:
    """Return a square avatar crop centred on the face (or a safe fallback).

    The crop is clamped to the image; the fallback uses the upper-middle part
    of the head silhouette so a photo without a detected face still avoids the
    top-left background/door-frame corner.
    """

    width, height = image_size
    if face_bbox is not None and not face_bbox.isEmpty():
        cx = face_bbox.center().x()
        cy = face_bbox.center().y()
        side = max(face_bbox.width(), face_bbox.height()) * (1.0 + margin)
    else:
        if head_bbox.isEmpty():
            head_bbox = QRect(0, 0, width, height)
        cx = head_bbox.center().x()
        # A head bbox starts at the hair/hat; the face is normally in the
        # lower-middle.  Bias down so the fallback does not frame the forehead
        # or the door/wall behind the hair.
        cy = head_bbox.top() + head_bbox.height() * 0.66
        side = min(head_bbox.width(), head_bbox.height()) * 0.68
    side = max(24, int(round(min(side, min(width, height)))))
    left = int(round(cx - side / 2))
    top = int(round(cy - side / 2))
    left = max(0, min(width - side, left))
    top = max(0, min(height - side, top))
    return QRect(left, top, side, side)
