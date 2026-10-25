"""Qt pixmap loading and layer composition."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from PyQt6.QtCore import QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap

from .config import Catalog, CharacterConfig, FoodItem, PropItem, WardrobeItem
from .sockets import MountPoint, mount_rect

log = logging.getLogger(__name__)

ASSET_DPR = 2.0


def _blank_pixmap(size: QSize) -> QPixmap:
    pix = QPixmap(size)
    pix.fill(Qt.GlobalColor.transparent)
    return pix


def load_pixmap(path: Path | None) -> QPixmap:
    if not path or not path.is_file():
        return QPixmap()
    return QPixmap(str(path))


def _pixmap_has_content(pixmap: QPixmap, threshold: int = 20) -> bool:
    """Cheap visible-pixel check used to detect corrupt/empty head layers."""

    if pixmap.isNull():
        return False
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = image.width(), image.height()
    if width < 2 or height < 2:
        return False
    stride = image.bytesPerLine()
    data = bytes(image.constBits().asstring(image.sizeInBytes()))
    step_x = max(1, width // 48)
    step_y = max(1, height // 48)
    for y in range(0, height, step_y):
        row = y * stride
        for x in range(0, width, step_x):
            if data[row + x * 4 + 3] > threshold:
                return True
    return False


class CommonAssets:
    """Assets shared by every character."""

    def __init__(self, catalog: Catalog, icon_path: Path) -> None:
        self.catalog = catalog
        self.icon = QIcon(str(icon_path)) if icon_path.is_file() else QIcon()
        self._pixmaps: dict[Path, QPixmap] = {}
        self._food_icons: dict[str, QIcon] = {}
        self._item_icons: dict[str, QIcon] = {}

    def pixmap(self, path: Path | None) -> QPixmap:
        if path is None:
            return QPixmap()
        path = Path(path)
        if path not in self._pixmaps:
            self._pixmaps[path] = load_pixmap(path)
        return self._pixmaps[path]

    def food_icon(self, food: FoodItem) -> QIcon:
        if food.id not in self._food_icons:
            self._food_icons[food.id] = QIcon(str(food.file))
        return self._food_icons[food.id]

    def wardrobe_icon(self, item: WardrobeItem) -> QIcon:
        if item.id not in self._item_icons:
            self._item_icons[item.id] = QIcon(str(item.file))
        return self._item_icons[item.id]


class CharacterAssets:
    """Compose body/head/wardrobe layers onto a transparent pet canvas."""

    def __init__(self, config: CharacterConfig, catalog: Catalog, common: CommonAssets) -> None:
        self.config = config
        self.catalog = catalog
        self.common = common
        self.canvas_w, self.canvas_h = config.canvas
        self.canvas_px = QSize(round(self.canvas_w * ASSET_DPR), round(self.canvas_h * ASSET_DPR))
        self._canvas_cache: dict[Path, QPixmap] = {}
        self._body_cache: dict[tuple[str, tuple[str, ...]], QPixmap] = {}
        self._head_cache: dict[tuple[str, tuple[str, ...]], QPixmap] = {}
        self._prop_cache: dict[str, QPixmap] = {}
        self._part_cache: dict[str, QPixmap] = {}

    # -- low level ------------------------------------------------------
    def _normalise(self, source: QPixmap) -> QPixmap:
        if source.isNull():
            return _blank_pixmap(self.canvas_px)
        target = _blank_pixmap(self.canvas_px)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(QRectF(0, 0, self.canvas_px.width(), self.canvas_px.height()), source, QRectF(source.rect()))
        painter.end()
        target.setDevicePixelRatio(ASSET_DPR)
        return target

    def canvas_layer(self, path: Path | None) -> QPixmap:
        if path is None:
            return _blank_pixmap(self.canvas_px)
        if path not in self._canvas_cache:
            self._canvas_cache[path] = self._normalise(load_pixmap(path))
        return self._canvas_cache[path]

    def _new_canvas(self) -> QPixmap:
        pix = _blank_pixmap(self.canvas_px)
        pix.setDevicePixelRatio(ASSET_DPR)
        return pix

    # -- articulated limbs ---------------------------------------------
    @property
    def has_rig(self) -> bool:
        return self.config.rig_enabled

    def part_pixmap(self, name: str) -> QPixmap:
        """One pivotable body layer, already normalised to the pet canvas."""

        if name in self._part_cache:
            return self._part_cache[name]
        path = self.config.parts.get(name)
        pix = self.canvas_layer(path) if path else _blank_pixmap(self.canvas_px)
        pix.setDevicePixelRatio(ASSET_DPR)
        self._part_cache[name] = pix
        return pix

    # -- anchor / socket mounting --------------------------------------
    def socket(self, name: str) -> MountPoint:
        return self.config.mount_point(name)

    def mounted_rect(
        self,
        mount_name: str,
        source: QPixmap,
        *,
        fit: float = 1.0,
        offset: tuple[float, float] = (0.0, 0.0),
        scale: float = 1.0,
    ) -> QRectF:
        """Design-space rectangle for a sprite mounted on a named socket."""

        if source.isNull():
            return QRectF()
        left, top, width, height = mount_rect(
            self.socket(mount_name),
            self.config.canvas,
            (source.width(), source.height()),
            fit=fit,
            offset=offset,
            scale=scale,
        )
        return QRectF(left, top, width, height)

    def draw_mounted(
        self,
        painter: QPainter,
        source: QPixmap,
        mount_name: str,
        *,
        fit: float = 1.0,
        offset: tuple[float, float] = (0.0, 0.0),
        scale: float = 1.0,
        rotation: float = 0.0,
        opacity: float = 1.0,
    ) -> QRectF:
        """Draw a standalone PNG centred on ``mount_name``.

        No geometry is painted here: the socket only supplies the destination
        rectangle, and every visible pixel comes from the external image.
        """

        if source.isNull():
            return QRectF()
        rect = self.mounted_rect(
            mount_name, source, fit=fit, offset=offset, scale=scale
        )
        if rect.isEmpty():
            return rect
        painter.save()
        if opacity < 1.0:
            painter.setOpacity(painter.opacity() * max(0.0, opacity))
        if abs(rotation) > 0.001:
            center = rect.center()
            painter.translate(center)
            painter.rotate(rotation)
            painter.translate(-center)
        painter.drawPixmap(rect, source, QRectF(source.rect()))
        painter.restore()
        return rect

    def _sprite(self, item: WardrobeItem) -> QPixmap:
        return self.common.pixmap(item.file)

    def draw_item(
        self,
        painter: QPainter,
        item: WardrobeItem | None,
        *,
        scale: float = 1.0,
        rotation: float = 0.0,
        opacity: float = 1.0,
    ) -> QRectF:
        if item is None or not item.is_accessory:
            return QRectF()
        return self.draw_mounted(
            painter,
            self._sprite(item),
            item.mount,
            fit=item.fit,
            offset=item.offset,
            scale=scale,
            rotation=rotation,
            opacity=opacity,
        )

    def draw_food(
        self,
        painter: QPainter,
        source: QPixmap,
        food: FoodItem | None = None,
        *,
        scale: float = 1.0,
        rotation: float = 0.0,
        opacity: float = 1.0,
    ) -> QRectF:
        if food is not None:
            mount_name, fit, offset = food.mount, food.fit, food.offset
        else:
            # Dropped files have no catalogue entry; they still use the same
            # mouth socket instead of a hard-coded pixel offset.
            mount_name, fit, offset = "mouth", 1.35, (0.0, 0.0)
        return self.draw_mounted(
            painter,
            source,
            mount_name,
            fit=fit,
            offset=offset,
            scale=scale,
            rotation=rotation,
            opacity=opacity,
        )

    # -- composition ----------------------------------------------------
    def body_pose_path(self, pose: str) -> Path | None:
        """Return the body texture for a pose, falling back to body.png."""

        return self.config.pose_path(pose)

    @staticmethod
    def _is_head_accessory(item: WardrobeItem) -> bool:
        # head_top and face live in the head layer so they follow head tilt.
        return item.mount in {"head_top", "face"}

    def _head_accessories(self, accessory_ids: Iterable[str]) -> list[WardrobeItem]:
        items: list[WardrobeItem] = []
        for item_id in set(accessory_ids):
            item = self.catalog.item(item_id)
            if item is not None and item.is_accessory and self._is_head_accessory(item):
                items.append(item)
        return sorted(items, key=lambda i: i.z)

    def _hand_accessories(self, accessory_ids: Iterable[str]) -> list[WardrobeItem]:
        items: list[WardrobeItem] = []
        for item_id in set(accessory_ids):
            item = self.catalog.item(item_id)
            if item is not None and item.is_accessory and item.mount == "hand":
                items.append(item)
        return sorted(items, key=lambda i: i.z)

    def draw_body_accessories(
        self,
        painter: QPainter,
        accessory_ids: Iterable[str],
        *,
        scale: float = 1.0,
    ) -> None:
        """Draw hand-held accessories centred on the ``hand`` socket."""

        for item in self._hand_accessories(accessory_ids):
            self.draw_item(painter, item, scale=scale)

    def compose_body(
        self,
        pose: str,
        accessory_ids: Iterable[str] = (),
    ) -> QPixmap:
        hand_accessories = self._hand_accessories(accessory_ids)
        key = (pose, tuple(item.id for item in hand_accessories))
        if key in self._body_cache:
            return self._body_cache[key]
        target = self._new_canvas()
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(0, 0, self.canvas_layer(self.body_pose_path(pose)))
        for item in hand_accessories:
            self.draw_item(painter, item)
        painter.end()
        self._body_cache[key] = target
        return target

    def _head_source(self, expression: str) -> QPixmap:
        """Pick a drawn head layer, skipping empty/corrupt expression files."""

        path = self.config.expression_path(expression)
        if path is None:
            return QPixmap()
        source = self.canvas_layer(path)
        if _pixmap_has_content(source):
            return source
        # A zero-byte or transparent file must never make the head disappear.
        for fallback in ("normal", "happy", "blink"):
            fallback_path = self.config.expression_path(fallback)
            if fallback_path is None or fallback_path == path:
                continue
            fallback_source = self.canvas_layer(fallback_path)
            if _pixmap_has_content(fallback_source):
                log.warning("%s：表情 %s 为空，改用 %s", self.config.name, expression, fallback)
                return fallback_source
        return source

    def compose_head(
        self,
        expression: str,
        accessory_ids: Iterable[str] = (),
    ) -> QPixmap:
        ids = tuple(sorted(set(accessory_ids)))
        key = (expression, ids)
        if key in self._head_cache:
            return self._head_cache[key]
        target = self._new_canvas()
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        source = self._head_source(expression)
        if not source.isNull():
            painter.drawPixmap(0, 0, source)
        for item in self._head_accessories(ids):
            self.draw_item(painter, item)
        painter.end()
        self._head_cache[key] = target
        return target

    # -- misc art --------------------------------------------------------
    def _prop_item(self, name: str) -> PropItem | None:
        item = self.catalog.prop(name)
        if item is not None:
            return item
        if name == "book" and self.catalog.book_file is not None:
            return PropItem(
                id="book",
                name="book",
                file=self.catalog.book_file,
                mount="hand",
                fit=1.25,
                offset=(0.0, -0.03),
            )
        return None

    def prop(self, name: str) -> QPixmap:
        """Return the standalone PNG for a prop (the study book by default)."""

        if name in self._prop_cache:
            return self._prop_cache[name]
        item = self._prop_item(name)
        pix = self.common.pixmap(item.file if item is not None else None)
        self._prop_cache[name] = pix
        return pix

    def draw_prop(
        self,
        painter: QPainter,
        name: str,
        *,
        scale: float = 1.0,
        rotation: float = 0.0,
    ) -> QRectF:
        item = self._prop_item(name)
        if item is None:
            return QRectF()
        return self.draw_mounted(
            painter,
            self.prop(name),
            item.mount,
            fit=item.fit,
            offset=item.offset,
            scale=scale,
            rotation=rotation,
        )

    def invalidate(self) -> None:
        self._body_cache.clear()
        self._head_cache.clear()
        self._part_cache.clear()
        self._prop_cache.clear()


def _head_image(config: CharacterConfig) -> QImage:
    """Face-centred avatar when the importer produced one, else head crop."""

    if config.avatar_path is not None and config.avatar_path.is_file():
        avatar = QImage(str(config.avatar_path))
        if not avatar.isNull():
            return avatar
    path = config.expression_path("happy") or config.expression_path("normal")
    if path is not None:
        image = QImage(str(path))
        if not image.isNull():
            left, top, width, height = config.head_rect
            crop = QRect(
                max(0, int(left * image.width())),
                max(0, int(top * image.height())),
                max(1, int(width * image.width())),
                max(1, int(height * image.height())),
            )
            return image.copy(crop.intersected(image.rect()))
    body = config.layer_path("body")
    image = QImage(str(body)) if body else QImage()
    if image.isNull():
        return QImage()
    # Single-layer characters (including imported ones): the configured head
    # rectangle is exactly the region we want in the round card.
    left, top, width, height = config.head_rect
    crop = QRect(
        int(left * image.width()),
        int(top * image.height()),
        max(1, int(width * image.width())),
        max(1, int(height * image.height())),
    ).intersected(image.rect())
    if not crop.isEmpty():
        return image.copy(crop)
    return image


def make_character_icon(config: CharacterConfig, size: int = 96) -> QIcon:
    """A small round avatar for tray/menu lists."""

    head = _head_image(config)
    if head.isNull():
        return QIcon()
    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    painter.setBrush(QColor(config.accent))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size * 2 - 4, size * 2 - 4)

    side = size * 2 - 18
    circle = QPainterPath()
    circle.addEllipse(QRectF(4, 4, size * 2 - 8, size * 2 - 8))
    painter.save()
    painter.setClipPath(circle)
    if config.avatar_path is not None and config.avatar_path.is_file():
        # The importer already cropped around the face; fill the circle.
        scaled = head.scaled(
            side,
            side,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        left = (size * 2 - scaled.width()) // 2
        top = (size * 2 - scaled.height()) // 2
        painter.drawImage(left, top, scaled)
    else:
        scaled = head.scaled(
            side,
            side,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawImage(
            (size * 2 - scaled.width()) // 2,
            (size * 2 - scaled.height()) // 2 - 2,
            scaled,
        )
    painter.restore()

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255, 170), 4))
    painter.drawEllipse(4, 4, size * 2 - 8, size * 2 - 8)
    painter.end()
    pix.setDevicePixelRatio(2.0)
    return QIcon(pix)
