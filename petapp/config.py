"""Configuration and content catalog loading."""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .motion import MotionProfile
from .sockets import (
    ACCESSORY_SLOTS,
    DEFAULT_FOOD_MOUNT,
    DEFAULT_PROP_MOUNT,
    MountPoint,
    clamp,
    default_mount_points,
    normalise_mount_points,
    normalise_offset,
    normalise_slot,
    resolve_mount_name,
)

log = logging.getLogger(__name__)

KNOWN_EXPRESSIONS = ("normal", "blink", "happy", "angry", "hit", "sleep", "eat", "sad", "smug")

#: Body textures a character may provide.  Every missing pose falls back to
#: ``body.png`` so a plain one-image character keeps working unchanged.
POSE_NAMES = ("idle", "sit", "walk_left", "walk_right", "drag")
POSE_ALIASES = {
    "stand": "idle",
    "walk": "walk_left",
    "dangle": "drag",
    "fall": "drag",
}

#: Characters that ship with the app.  These are the "system initial"
#: classmates: they can be hidden/re-summoned but never deleted from the
#: settings panel.  The slugs are stable across translations.
SYSTEM_CHARACTER_SLUGS: tuple[str, ...] = ("xiaoman", "laowang", "linlin", "elaina")
SYSTEM_CHARACTER_NAMES: tuple[str, ...] = ("小满", "老王", "林林", "伊蕾娜")
#: Backwards-friendly aliases for callers that used another name.
INITIAL_CHARACTER_SLUGS = SYSTEM_CHARACTER_SLUGS
PROTECTED_CHARACTER_SLUGS = SYSTEM_CHARACTER_SLUGS
BUILTIN_CHARACTER_SLUGS = SYSTEM_CHARACTER_SLUGS
INITIAL_CHARACTER_NAMES = SYSTEM_CHARACTER_NAMES


def is_system_character(character_or_slug: Any) -> bool:
    """True for the four bundled classmates (by slug or config object)."""

    slug = getattr(character_or_slug, "slug", character_or_slug)
    return str(slug or "").strip() in SYSTEM_CHARACTER_SLUGS


#: Readable aliases used by tests / integrations.
is_initial_character = is_system_character
is_builtin_character = is_system_character


def _as_bool(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "system", "builtin", "protected"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return fallback
    return bool(value)
DEFAULT_ACCENT = "#7B68EE"
DEFAULT_CANVAS = (360.0, 540.0)
DEFAULT_HEAD_RECT = (0.14, 0.025, 0.72, 0.46)
DEFAULT_BODY_RECT = (0.15, 0.48, 0.70, 0.50)
DEFAULT_MOUTH = (0.5, 0.4)

#: Display size.  The desktop pet is meant to be a small desk ornament, so a
#: fresh character starts at 40% and can shrink to a 20% corner charm.
DEFAULT_SCALE = 0.4
MIN_SCALE = 0.2
MAX_SCALE = 2.0

#: Optional articulated layers.  All five must exist for the ragdoll rig to be
#: used; otherwise the app falls back to the classic single body layer.
RIG_PART_NAMES = ("torso", "arm_left", "arm_right", "leg_left", "leg_right")
DEFAULT_RIG_PIVOTS: dict[str, tuple[float, float]] = {
    "torso": (0.5, 0.775),
    "arm_left": (0.3333, 0.5481),
    "arm_right": (0.6667, 0.5481),
    "leg_left": (0.4194, 0.7778),
    "leg_right": (0.5806, 0.7778),
    "head": (0.5, 0.4556),
}

DEFAULT_LINES: dict[str, list[str]] = {
    "greet": ["我来啦。右边托盘可以召唤更多室友，右键我还能换装。"],
    "idle": ["今天也是摸鱼的一天。", "桌面挺干净，适合躺平。"],
    "poke": ["别戳啦！", "再戳我要生气了。", "你手怎么这么欠呢？"],
    "body": ["喂，摸哪儿呢？", "别乱戳，我这纸片身子金贵着呢。"],
    "anger": ["我火气上来了啊。", "你最好现在停手。"],
    "pat": ["唔……再摸一下。", "摸头可以，给钱就免了。"],
    "drag": ["放我下来！我恐高！", "救命，有人拎纸片人啦！"],
    "drop": ["哎哟！", "地板好硬。"],
    "feed": ["谢谢，真香。", "这顿可以。"],
    "spit": ["呸，这不能吃！", "你管这叫饭？"],
    "file_eat": ["文件？我啃了。", "嘎嘣脆，像你的作业。"],
    "too_big": ["这也太大了，我嘴小！"],
    "sleep": ["晚安，别叫我。", "充会儿电。"],
    "wake": ["嗯？几点了？", "我刚刚没睡，在思考人生。"],
    "rage": ["你完蛋了！", "忍无可忍！"],
    "work": ["又在卷，注意休息。", "写代码辛苦了。"],
    "play": ["又在摸鱼？", "玩得开心，记得看看我。"],
    "hungry": ["肚子饿了，投喂一下？", "我听见你抽屉里的零食了。"],
    "study": ["陪你学一会儿。"],
    "study_end": ["学完了，奖励呢？"],
    "pat_all": ["排队排队，一个一个来。"],
    "welcome_hint": ["右键可以打开菜单；右下角托盘能召唤其他同学哦。"],
}


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_rect(value: Any, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    try:
        rect = tuple(max(0.0, min(1.0, float(v))) for v in value)
        if len(rect) != 4:
            raise ValueError
        left, top, width, height = rect
        width = max(0.05, min(1.0 - left, width))
        height = max(0.05, min(1.0 - top, height))
        return (left, top, width, height)
    except (TypeError, ValueError):
        return fallback


def _as_point(value: Any, fallback: tuple[float, float]) -> tuple[float, float]:
    try:
        point = tuple(max(0.0, min(1.0, float(v))) for v in value)
        if len(point) != 2:
            raise ValueError
        return (point[0], point[1])
    except (TypeError, ValueError):
        return fallback


def _normalise_lines(raw: Any) -> dict[str, list[str]]:
    merged = {key: list(values) for key, values in DEFAULT_LINES.items()}
    if not isinstance(raw, dict):
        return merged
    for key, values in raw.items():
        if not isinstance(key, str):
            continue
        if isinstance(values, str):
            values = [values]
        if isinstance(values, (list, tuple)):
            cleaned = [str(item).strip() for item in values if str(item).strip()]
            if cleaned:
                merged[key] = cleaned
    return merged


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise ValueError(f"无法读取 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("配置文件顶层必须是 JSON 对象")
    return data


@dataclass
class CharacterConfig:
    slug: str
    name: str
    subtitle: str
    folder: Path
    order: float = 0.0
    scale: float = 0.86
    temper: float = 1.0
    accent: str = DEFAULT_ACCENT
    canvas: tuple[float, float] = DEFAULT_CANVAS
    head_rect: tuple[float, float, float, float] = DEFAULT_HEAD_RECT
    body_rect: tuple[float, float, float, float] = DEFAULT_BODY_RECT
    mouth: tuple[float, float] = DEFAULT_MOUTH
    #: Named attachment points used by wardrobe, food and props.  Values are
    #: normalised to the design canvas; see :mod:`petapp.sockets`.
    mount_points: dict[str, MountPoint] = field(default_factory=dict)
    layer_files: dict[str, str] = field(default_factory=dict)
    #: Discovered dedicated pose textures (idle / sit / walk_left / walk_right
    #: / drag).  Missing entries fall back to the normal body sprite.
    poses: dict[str, Path] = field(default_factory=dict)
    #: Packager metadata for imported tall/photo characters.  The head art is
    #: already baked at this scale, so runtime painting only reads it for
    #: diagnostics.
    big_head: bool = False
    head_scale: float = 1.0
    skeleton_file: Path | None = None
    skeleton: dict[str, Any] = field(default_factory=dict)
    avatar_path: Path | None = None
    cutout_method: str = ""
    #: Lock the face to the untouched ``head.png`` (no blink/angry/sleep
    #: expression swaps).  Set by characters whose expression heads were
    #: auto-derived rather than hand-drawn.
    face_static: bool = False
    expressions: dict[str, Path] = field(default_factory=dict)
    lines: dict[str, list[str]] = field(default_factory=lambda: _normalise_lines({}))
    starting_accessories: tuple[str, ...] = ()
    bust_mode: bool = False
    #: Bundled initial character.  Locked against deletion in the manager.
    system: bool = False
    voice_gain: float = 0.8
    parts: dict[str, Path] = field(default_factory=dict)
    rig_pivots: dict[str, tuple[float, float]] = field(
        default_factory=lambda: dict(DEFAULT_RIG_PIVOTS)
    )
    motion: MotionProfile = field(default_factory=MotionProfile)
    rage_threshold: float = 99.5
    raw: dict[str, Any] = field(default_factory=dict)

    # -- convenience ----------------------------------------------------
    @property
    def rig_enabled(self) -> bool:
        """True when every articulated layer needed by the ragdoll exists."""

        return all(name in self.parts for name in RIG_PART_NAMES)

    def pivot(self, name: str) -> tuple[float, float]:
        return self.rig_pivots.get(name, DEFAULT_RIG_PIVOTS.get(name, (0.5, 0.5)))

    @property
    def posture(self) -> str:
        """``"sit"`` for a desk-hugging portrait, otherwise ``"stand"``."""

        return "sit" if self.bust_mode else "stand"

    @property
    def is_system(self) -> bool:
        return self.system or self.slug in SYSTEM_CHARACTER_SLUGS

    @property
    def deletable(self) -> bool:
        return not self.is_system

    def mount_point(self, name: str) -> MountPoint:
        """Return a named socket, falling back to a usable head anchor.

        Accessories may only target ``head_top`` / ``face`` / ``hand``; a typo
        or a legacy ``torso`` request must never resurrect the old clothing
        overlay, so it resolves to the closest real socket instead.
        """

        requested = str(name or "").strip()
        point = self.mount_points.get(requested)
        if point is not None:
            return point
        key = resolve_mount_name(requested, self.mount_points) or "head_top"
        point = self.mount_points.get(key)
        if point is not None:
            return point
        return MountPoint(key, 0.5, 0.5, 0.25)

    def pick_line(self, kind: str, fallback: str = "idle", rng: random.Random | None = None) -> str:
        rng = rng or random
        choices = self.lines.get(kind) or self.lines.get(fallback) or DEFAULT_LINES["idle"]
        return rng.choice(choices)

    def has_line(self, kind: str) -> bool:
        return bool(self.lines.get(kind))

    def expression_path(self, expression: str) -> Path | None:
        if expression in self.expressions:
            return self.expressions[expression]
        return self.expressions.get("normal")

    def layer_path(self, role: str) -> Path | None:
        rel = self.layer_files.get(role)
        if not rel:
            return None
        path = self.folder / rel
        return path if path.exists() else None

    def pose_path(self, pose: str) -> Path | None:
        """Body texture for one pose, falling back to ``body.png``.

        A folder with only ``body.png`` therefore serves every pose with the
        same default sprite; adding ``sit.png`` / ``walk.png`` / ``drag.png``
        automatically lights up the corresponding pose.
        """

        key = POSE_ALIASES.get(str(pose or "").strip().lower(), str(pose or "").strip().lower())
        if key in self.poses:
            return self.poses[key]
        if key == "walk_left" and "walk_right" in self.poses:
            return self.poses["walk_right"]
        if key == "walk_right" and "walk_left" in self.poses:
            return self.poses["walk_left"]
        return self.layer_path("body")

    @property
    def has_costumes(self) -> bool:
        """Only characters with a local ``costumes/`` pack may open 换装."""

        try:
            return (self.folder / "costumes").is_dir()
        except OSError:
            return False

    def has_dedicated_pose(self, pose: str) -> bool:
        """True when ``pose`` has its own texture, not just the body fallback."""

        key = POSE_ALIASES.get(str(pose or "").strip().lower(), str(pose or "").strip().lower())
        path = self.poses.get(key)
        body = self.layer_path("body")
        return path is not None and (body is None or path.resolve() != body.resolve())

    def all_files(self) -> Iterable[Path]:
        yield from self.expressions.values()
        yield from self.parts.values()
        yield from self.poses.values()
        if self.skeleton_file is not None:
            yield self.skeleton_file
        if self.avatar_path is not None:
            yield self.avatar_path
        for role in ("body", "walk", "dangle"):
            path = self.layer_path(role)
            if path:
                yield path


@dataclass
class WardrobeItem:
    id: str
    name: str
    category: str
    slot: str
    file: Path
    z: int
    description: str = ""
    #: Socket name plus its scaling/offset metadata.  The PNG itself is a
    #: standalone sprite; it is never a pre-aligned full-canvas overlay.
    mount: str = "head_top"
    fit: float = 1.0
    offset: tuple[float, float] = (0.0, 0.0)

    @property
    def is_accessory(self) -> bool:
        """Only the three small sockets are valid wardrobe slots."""

        if self.mount not in ACCESSORY_SLOTS:
            return False
        return normalise_slot(self.slot or self.mount) == self.mount


@dataclass
class FoodItem:
    id: str
    name: str
    file: Path
    hunger: float
    energy: float
    anger: float
    description: str = ""
    mount: str = DEFAULT_FOOD_MOUNT
    fit: float = 1.0
    offset: tuple[float, float] = (0.0, 0.0)


@dataclass
class PropItem:
    id: str
    name: str
    file: Path
    mount: str = DEFAULT_PROP_MOUNT
    fit: float = 1.0
    offset: tuple[float, float] = (0.0, 0.0)


@dataclass
class Catalog:
    items: dict[str, WardrobeItem] = field(default_factory=dict)
    foods: dict[str, FoodItem] = field(default_factory=dict)
    props: dict[str, PropItem] = field(default_factory=dict)
    book_file: Path | None = None
    #: Small ambient sprite used by the window (sweat drop while held).
    sweat_file: Path | None = None

    @classmethod
    def load(cls, items_dir: Path) -> "Catalog":
        catalog_file = items_dir / "catalog.json"
        if not catalog_file.exists():
            raise FileNotFoundError(f"缺少素材目录文件：{catalog_file}")
        data = _read_json(catalog_file)
        result = cls()
        sweat = items_dir / "sweat.png"
        if sweat.is_file():
            result.sweat_file = sweat
        for raw in data.get("items", []):
            if not isinstance(raw, dict):
                continue
            item_id = str(raw.get("id", "")).strip()
            path = items_dir / str(raw.get("file", ""))
            if not item_id or not path.is_file():
                log.warning("跳过无效衣物素材：%s", raw)
                continue
            slot = normalise_slot(raw.get("slot"))
            mount = normalise_slot(raw.get("mount", slot), slot)
            if not mount:
                # Legacy outfit / torso entries are skipped, not drawn.  This
                # is what keeps a stale catalogue from painting a rectangle
                # over a character with a non-standard silhouette.
                log.warning("跳过不支持的装扮插槽：%s", raw)
                continue
            result.items[item_id] = WardrobeItem(
                id=item_id,
                name=str(raw.get("name", item_id)),
                category=str(raw.get("category", "小挂件")),
                slot=mount,
                file=path,
                z=int(raw.get("z", 30)),
                description=str(raw.get("description", "")),
                mount=mount,
                fit=clamp(_as_float(raw.get("fit"), 1.0), 0.02, 4.0),
                offset=normalise_offset(raw.get("offset")),
            )
        for raw in data.get("foods", []):
            if not isinstance(raw, dict):
                continue
            food_id = str(raw.get("id", "")).strip()
            path = items_dir / str(raw.get("file", ""))
            if not food_id or not path.is_file():
                log.warning("跳过无效食物素材：%s", raw)
                continue
            food_mount = str(raw.get("mount", DEFAULT_FOOD_MOUNT)).strip()
            if food_mount != DEFAULT_FOOD_MOUNT:
                food_mount = DEFAULT_FOOD_MOUNT
            result.foods[food_id] = FoodItem(
                id=food_id,
                name=str(raw.get("name", food_id)),
                file=path,
                hunger=_as_float(raw.get("hunger"), 12),
                energy=_as_float(raw.get("energy"), 3),
                anger=_as_float(raw.get("anger"), 0),
                description=str(raw.get("description", "")),
                # Food is always eaten at the mouth socket; never a torso
                # overlay.  Unknown values fall back instead of drifting.
                mount=food_mount,
                fit=clamp(_as_float(raw.get("fit"), 1.0), 0.02, 4.0),
                offset=normalise_offset(raw.get("offset"), (0.0, 0.0)),
            )
        props = data.get("props", {})
        if isinstance(props, dict):
            for prop_id, raw in props.items():
                if not isinstance(prop_id, str):
                    continue
                # Accept the old ``"book": "book.png"`` shorthand as well.
                if isinstance(raw, str):
                    raw = {"file": raw}
                if not isinstance(raw, dict):
                    continue
                path = items_dir / str(raw.get("file", f"{prop_id}.png"))
                if not path.is_file():
                    log.warning("跳过无效道具素材：%s", raw)
                    continue
                prop_mount = str(raw.get("mount", DEFAULT_PROP_MOUNT)).strip()
                if prop_mount != DEFAULT_PROP_MOUNT:
                    prop_mount = DEFAULT_PROP_MOUNT
                result.props[prop_id] = PropItem(
                    id=prop_id,
                    name=str(raw.get("name", prop_id)),
                    file=path,
                    mount=prop_mount,
                    fit=clamp(_as_float(raw.get("fit"), 1.0), 0.02, 4.0),
                    offset=normalise_offset(raw.get("offset")),
                )
            book = result.props.get("book")
            if book is not None:
                result.book_file = book.file
        return result

    def item(self, item_id: str) -> WardrobeItem | None:
        return self.items.get(item_id)

    def food(self, food_id: str) -> FoodItem | None:
        return self.foods.get(food_id)

    def prop(self, prop_id: str) -> PropItem | None:
        return self.props.get(prop_id)

    def categories(self) -> list[tuple[str, list[WardrobeItem]]]:
        groups: dict[str, list[WardrobeItem]] = {}
        for item in self.items.values():
            groups.setdefault(item.category, []).append(item)
        return [(name, sorted(items, key=lambda i: i.name)) for name, items in groups.items()]


def _discover_expressions(folder: Path, raw: dict[str, Any]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    configured = raw.get("expressions", {})
    if isinstance(configured, dict):
        for name, rel in configured.items():
            if not isinstance(rel, str):
                continue
            path = folder / rel
            if path.is_file():
                result[str(name)] = path
    heads_dir = folder / "heads"
    if heads_dir.is_dir():
        for path in sorted(heads_dir.glob("*.png")):
            result.setdefault(path.stem, path)
    if "normal" not in result:
        fallback = folder / "head.png"
        if fallback.is_file():
            result["normal"] = fallback
    return result


def _discover_parts(folder: Path, raw: dict[str, Any]) -> dict[str, Path]:
    """Find the optional articulated layers.

    Layered art wins over the classic body sprite only when all five parts are
    present.  Both explicit ``parts`` entries and the conventional
    ``parts/<name>.png`` files are accepted.
    """

    configured = raw.get("parts", {})
    if not isinstance(configured, dict):
        configured = {}
    result: dict[str, Path] = {}
    for name in RIG_PART_NAMES:
        rel = configured.get(name)
        if isinstance(rel, str) and rel.strip():
            path = folder / rel
            if path.is_file():
                result[name] = path
        if name not in result:
            automatic = folder / "parts" / f"{name}.png"
            if automatic.is_file():
                result[name] = automatic
    return result


def _discover_poses(
    folder: Path,
    raw: dict[str, Any],
    layer_files: Mapping[str, str],
) -> dict[str, Path]:
    """Find optional pose body textures.

    Resolution order: explicit ``poses`` entries, conventional files
    (``sit.png``, ``walk.png``, ``walk_left.png`` ……), then the legacy
    ``layers.walk`` / ``layers.dangle`` entries.  A path equal to the normal
    body is treated as a fallback, so later-added conventional files can still
    override it.  Missing poses are simply absent from the returned mapping and
    :meth:`CharacterConfig.pose_path` falls back to ``body.png``.
    """

    body_path = folder / layer_files.get("body", "body.png")
    result: dict[str, Path] = {}

    configured = raw.get("poses")
    if isinstance(configured, Mapping):
        for name, relative in configured.items():
            key = POSE_ALIASES.get(str(name).strip().lower(), str(name).strip().lower())
            if key not in POSE_NAMES or not isinstance(relative, str):
                continue
            path = folder / relative
            if path.is_file():
                result[key] = path

    conventional = {
        "idle": ("idle.png",),
        "sit": ("sit.png", "seat.png"),
        "walk_left": ("walk_left.png", "walk.png"),
        "walk_right": ("walk_right.png", "walk.png"),
        "drag": ("drag.png", "dangle.png"),
    }
    legacy_walk = folder / layer_files.get("walk", "body.png")
    legacy_dangle = folder / layer_files.get("dangle", "body.png")
    for key, candidates in conventional.items():
        current = result.get(key)
        overridable = {body_path.resolve()}
        if key in {"walk_left", "walk_right"}:
            overridable.add(legacy_walk.resolve())
        elif key == "drag":
            overridable.add(legacy_dangle.resolve())
        if current is not None and current.resolve() not in overridable:
            continue
        for relative in candidates:
            path = folder / relative
            if path.is_file():
                result[key] = path
                break

    if legacy_walk.is_file() and legacy_walk.resolve() != body_path.resolve():
        result.setdefault("walk_left", legacy_walk)
        result.setdefault("walk_right", legacy_walk)
    if legacy_dangle.is_file() and legacy_dangle.resolve() != body_path.resolve():
        result.setdefault("drag", legacy_dangle)

    # Every pose stays addressable even when it falls back to body.png.  This
    # keeps ``config.poses`` introspectable while has_dedicated_pose() still
    # distinguishes a real pose texture from the shared default.
    for key in POSE_NAMES:
        result.setdefault(key, body_path)
    return result


def _discover_rig_pivots(raw: dict[str, Any]) -> dict[str, tuple[float, float]]:
    configured = raw.get("rig", {})
    if not isinstance(configured, dict):
        configured = {}
    pivots_raw = configured.get("pivots", {})
    if not isinstance(pivots_raw, dict):
        pivots_raw = {}
    pivots: dict[str, tuple[float, float]] = {}
    for name, fallback in DEFAULT_RIG_PIVOTS.items():
        pivots[name] = _as_point(pivots_raw.get(name), fallback)
    return pivots


def load_character(folder: Path) -> CharacterConfig:
    config_file = folder / "config.json"
    if not config_file.is_file():
        raise FileNotFoundError(f"缺少 {config_file}")
    raw = _read_json(config_file)
    name = str(raw.get("name", folder.name)).strip() or folder.name
    slug = str(raw.get("slug", folder.name)).strip() or folder.name
    slug = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]+", "_", slug)
    accent = str(raw.get("accent", DEFAULT_ACCENT))
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", accent):
        accent = DEFAULT_ACCENT
    canvas_raw = raw.get("canvas", DEFAULT_CANVAS)
    try:
        canvas = (max(100.0, float(canvas_raw[0])), max(100.0, float(canvas_raw[1])))
    except (TypeError, ValueError, IndexError):
        canvas = DEFAULT_CANVAS

    layers_raw = raw.get("layers", {})
    if not isinstance(layers_raw, dict):
        layers_raw = {}
    layer_files = {
        "body": str(layers_raw.get("body", "body.png")),
        "walk": str(layers_raw.get("walk", layers_raw.get("body", "body.png"))),
        "dangle": str(layers_raw.get("dangle", layers_raw.get("body", "body.png"))),
    }
    body_path = folder / layer_files["body"]
    if not body_path.is_file():
        # Permissive fallback: use any PNG big enough to be a body sprite.
        candidates = [p for p in folder.glob("*.png") if p.name not in {"icon.png"}]
        if not candidates:
            raise ValueError(f"{folder.name}：找不到身体图层 body.png")
        layer_files["body"] = candidates[0].name
        layer_files["walk"] = candidates[0].name
        layer_files["dangle"] = candidates[0].name
        log.warning("%s：body.png 缺失，暂用 %s", folder.name, candidates[0].name)

    poses = _discover_poses(folder, raw, layer_files)
    expressions = _discover_expressions(folder, raw)
    if not expressions:
        log.info("%s：没有头部表情图层，按单图层角色显示", folder.name)

    skeleton_file: Path | None = None
    skeleton: dict[str, Any] = {}
    skeleton_rel = raw.get("skeleton", "skeleton.json")
    if isinstance(skeleton_rel, str):
        candidate = folder / skeleton_rel
        if candidate.is_file():
            try:
                loaded = _read_json(candidate)
                if isinstance(loaded, dict):
                    skeleton_file = candidate
                    skeleton = loaded
            except Exception as exc:
                log.warning("%s：骨骼网格配置无法读取：%s", folder.name, exc)

    avatar_path: Path | None = None
    avatar_rel = raw.get("avatar", "avatar.png")
    if isinstance(avatar_rel, str):
        candidate = folder / avatar_rel
        if candidate.is_file():
            avatar_path = candidate
    cutout_method = str(raw.get("cutout", "") or "")

    starting_accessories_raw = raw.get("starting_accessories", [])
    if isinstance(starting_accessories_raw, str):
        starting_accessories_raw = [starting_accessories_raw]
    starting_accessories = tuple(str(v) for v in starting_accessories_raw if isinstance(v, str))
    if not (folder / "costumes").is_dir():
        # A single-image/custom character without a costume pack must never
        # inherit catalogue wigs/shades from a stale config.
        starting_accessories = ()

    head_rect = _as_rect(raw.get("head_rect"), DEFAULT_HEAD_RECT)
    body_rect = _as_rect(raw.get("body_rect"), DEFAULT_BODY_RECT)
    mouth = _as_point(raw.get("mouth"), DEFAULT_MOUTH)
    mount_points = normalise_mount_points(
        raw.get("mount_points"),
        default_mount_points(head_rect, body_rect, mouth),
    )
    posture_raw = str(raw.get("posture", "")).strip().lower()
    bust_mode = _as_bool(raw.get("bust_mode"), False) or posture_raw in {
        "sit",
        "sitting",
        "desk",
        "坐姿",
        "坐姿趴桌",
    }
    system = _as_bool(
        raw.get("system", raw.get("builtin", raw.get("protected", False))),
        False,
    ) or slug in SYSTEM_CHARACTER_SLUGS

    return CharacterConfig(
        slug=slug,
        name=name,
        subtitle=str(raw.get("subtitle", "宿舍在逃纸片人")),
        folder=folder,
        order=_as_float(raw.get("order"), 0.0),
        scale=max(0.5, min(1.35, _as_float(raw.get("scale"), 0.86))),
        temper=max(0.2, min(2.5, _as_float(raw.get("temper"), 1.0))),
        accent=accent,
        canvas=canvas,
        head_rect=head_rect,
        body_rect=body_rect,
        mouth=mouth,
        mount_points=mount_points,
        layer_files=layer_files,
        poses=poses,
        big_head=_as_bool(raw.get("big_head"), False),
        head_scale=max(1.0, min(2.0, _as_float(raw.get("head_scale"), 1.0))),
        skeleton_file=skeleton_file,
        skeleton=skeleton,
        avatar_path=avatar_path,
        cutout_method=cutout_method,
        face_static=bool(raw.get("face_static", False)),
        expressions=expressions,
        lines=_normalise_lines(raw.get("lines")),
        starting_accessories=starting_accessories,
        bust_mode=bust_mode,
        system=system,
        voice_gain=max(0.0, min(1.0, _as_float(raw.get("voice_gain"), 0.8))),
        parts=_discover_parts(folder, raw),
        rig_pivots=_discover_rig_pivots(raw),
        motion=MotionProfile.from_mapping(raw.get("motion")),
        rage_threshold=max(
            1.0, min(100.0, _as_float(raw.get("rage_threshold"), 99.5))
        ),
        raw=raw,
    )


def load_characters(characters_dir: Path) -> list[CharacterConfig]:
    result: list[CharacterConfig] = []
    if not characters_dir.is_dir():
        return result
    for folder in sorted(characters_dir.iterdir()):
        if not folder.is_dir():
            continue
        try:
            result.append(load_character(folder))
        except Exception as exc:
            log.exception("加载角色失败 %s：%s", folder.name, exc)
    result.sort(key=lambda c: (c.order, c.name))
    return result


# ---------------------------------------------------------------------------
# global preferences
# ---------------------------------------------------------------------------


@dataclass
class Settings:
    sound_enabled: bool = True
    mischief_enabled: bool = True
    auto_watch: bool = True
    max_pets: int = 4
    last_character: str = ""
    first_run: bool = True
    # Per-character display scale chosen in the settings panel.
    scales: dict[str, float] = field(default_factory=dict)

    def scale_for(self, slug: str, fallback: float) -> float:
        value = self.scales.get(slug)
        if value is None:
            return DEFAULT_SCALE
        return max(MIN_SCALE, min(MAX_SCALE, float(value)))

    @classmethod
    def load(cls, path: Path) -> "Settings":
        if not path.is_file():
            return cls()
        try:
            raw = _read_json(path)
        except Exception as exc:
            log.warning("设置文件损坏，使用默认值：%s", exc)
            return cls()
        settings = cls()
        for field_name in (
            "sound_enabled",
            "mischief_enabled",
            "auto_watch",
            "first_run",
        ):
            if field_name in raw:
                setattr(settings, field_name, bool(raw[field_name]))
        if "max_pets" in raw:
            try:
                settings.max_pets = max(1, min(6, int(raw["max_pets"])))
            except (TypeError, ValueError):
                pass
        if isinstance(raw.get("last_character"), str):
            settings.last_character = raw["last_character"]
        scales_raw = raw.get("scales")
        if isinstance(scales_raw, dict):
            for slug, value in scales_raw.items():
                if not isinstance(slug, str):
                    continue
                try:
                    scale = float(value)
                except (TypeError, ValueError):
                    continue
                settings.scales[slug] = max(MIN_SCALE, min(MAX_SCALE, scale))
        return settings

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
