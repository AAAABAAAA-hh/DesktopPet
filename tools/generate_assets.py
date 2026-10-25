"""Regenerate the bundled placeholder characters, sounds, configs and previews.

Usage:
    python tools/generate_assets.py

Wardrobe, food and prop art is deliberately **not** drawn here.  Those are
external, independently authored PNG sprites described by
``assets/items/catalog.json``; this script only verifies that every referenced
file exists, so it can never overwrite them with procedural geometry.

The script is intentionally self-contained (Pillow required).  It never
touches user-provided replacements outside characters/ and assets/.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import struct
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from artkit import (  # noqa: E402
    DESIGN_H,
    DESIGN_W,
    alpha_bbox,
)
from character_art import PROFILES, RIG_PARTS, RIG_PIVOTS, build_all_characters  # noqa: E402
from petapp.motion import MotionProfile  # noqa: E402
from petapp.sockets import (  # noqa: E402
    MountPoint,
    default_mount_points,
    mount_rect,
    normalise_mount_points,
)

ASSETS = ROOT / "assets"
ITEMS = ASSETS / "items"
SOUNDS = ASSETS / "sounds"
CHARS = ROOT / "characters"
SHOTS = ROOT / "screenshots"

EXPRESSIONS = ["normal", "blink", "happy", "angry", "hit", "sleep", "eat", "sad", "smug"]
MOUTH_FRACTION = [0.5, 0.4]
HEAD_RECT = [0.14, 0.025, 0.72, 0.46]
BODY_RECT = [0.15, 0.48, 0.70, 0.50]


# ---------------------------------------------------------------------------
# audio
# ---------------------------------------------------------------------------


def _write_wav(path: Path, samples: list[float], rate: int = 22050) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    peak = max(0.001, max(abs(s) for s in samples))
    # winsound has no per-app volume control, so keep the bundled clips quiet.
    scale = min(1.0, 0.18 / peak)
    data = bytearray()
    for s in samples:
        v = int(max(-1.0, min(1.0, s * scale)) * 32000)
        data += struct.pack("<h", v)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(bytes(data))


def _tone_sequence(
    notes: list[tuple[float, float, float]],
    rate: int = 22050,
    gap: float = 0.0,
) -> list[float]:
    out: list[float] = []
    for freq, duration, amplitude in notes:
        count = int(rate * duration)
        for i in range(count):
            t = i / rate
            env = math.sin(math.pi * min(1.0, t / duration))
            if duration > 0:
                env *= max(0.0, 1.0 - t / duration) ** 0.35
            out.append(amplitude * env * math.sin(2 * math.pi * freq * t))
        if gap:
            out.extend([0.0] * int(rate * gap))
    return out


def _babble(pitch: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    rate = 22050
    out: list[float] = []
    # formant-ish vowel syllables
    for _ in range(rng.randint(4, 6)):
        duration = rng.uniform(0.055, 0.11)
        f0 = rng.uniform(180, 290) * pitch
        f1 = rng.uniform(520, 980) * (pitch ** 0.4)
        f2 = rng.uniform(1100, 1850) * (pitch ** 0.3)
        count = int(rate * duration)
        phase = 0.0
        for i in range(count):
            t = i / rate
            vib = 1.0 + 0.03 * math.sin(2 * math.pi * 6.0 * t)
            env = math.sin(math.pi * min(1.0, t / duration)) ** 0.6
            phase += 2 * math.pi * f0 * vib / rate
            s = (
                0.55 * math.sin(phase)
                + 0.24 * math.sin(2 * math.pi * f1 * t)
                + 0.12 * math.sin(2 * math.pi * f2 * t)
                + 0.04 * rng.uniform(-1, 1)
            )
            out.append(0.18 * env * s)
        silence = rng.uniform(0.008, 0.03)
        out.extend([0.0] * int(rate * silence))
    return out


def _crunch(seed: int = 9) -> list[float]:
    rng = random.Random(seed)
    rate = 22050
    out: list[float] = []
    for burst in range(4):
        count = int(rate * rng.uniform(0.04, 0.08))
        for i in range(count):
            t = i / rate
            env = (1 - i / count) ** 2
            out.append(env * rng.uniform(-0.28, 0.28) * (0.6 + 0.4 * math.sin(2 * math.pi * 60 * t)))
        out.extend([0.0] * int(rate * rng.uniform(0.01, 0.03)))
    return out


def build_sounds() -> None:
    SOUNDS.mkdir(parents=True, exist_ok=True)
    _write_wav(SOUNDS / "pop.wav", _tone_sequence([(680, 0.08, 0.2), (420, 0.12, 0.15)]))
    _write_wav(SOUNDS / "pat.wav", _tone_sequence([(880, 0.09, 0.14), (1160, 0.14, 0.10)], gap=0.02))
    _write_wav(SOUNDS / "eat.wav", _crunch())
    _write_wav(SOUNDS / "summon.wav", _tone_sequence([(523, 0.1, 0.1), (659, 0.1, 0.12), (784, 0.18, 0.15)]))
    _write_wav(SOUNDS / "whoosh.wav", _tone_sequence([(300, 0.12, 0.08), (220, 0.16, 0.06)]))
    _write_wav(SOUNDS / "rage.wav", _tone_sequence([(220, 0.12, 0.2), (294, 0.12, 0.22), (370, 0.28, 0.25)]))
    _write_wav(SOUNDS / "sparkle.wav", _tone_sequence([(1200, 0.08, 0.08), (1600, 0.08, 0.07), (2100, 0.16, 0.05)]))

    # Per-character "voice" clips. They are intentionally cartoonish chirps;
    # users can drop in real recordings with the same file names.
    for profile in PROFILES:
        voice_dir = CHARS / profile["slug"] / "voice"
        voice_dir.mkdir(parents=True, exist_ok=True)
        for i in range(1, 4):
            _write_wav(voice_dir / f"voice_{i}.wav", _babble(profile["voice_pitch"], seed=profile["order"] * 17 + i))
        _write_wav(voice_dir / "angry.wav", _babble(profile["voice_pitch"] * 1.18, seed=profile["order"] * 31 + 8))
        _write_wav(voice_dir / "happy.wav", _babble(profile["voice_pitch"] * 1.28, seed=profile["order"] * 13 + 3))
        _write_wav(voice_dir / "sleep.wav", _tone_sequence([(260, 0.22, 0.05), (220, 0.25, 0.04), (180, 0.35, 0.03)]))


# ---------------------------------------------------------------------------
# character configs
# ---------------------------------------------------------------------------


def write_character_config(profile: dict, char_dir: Path) -> None:
    base_lines = {
        "greet": [
            f"我是{profile['name']}，{profile['subtitle']}。以后就在你桌面混了。",
            "新窝不错，就是有点反光。",
        ],
        "file_eat": [
            "这文件……嘎嘣脆。",
            "你的作业味道不错，下次还做这个。",
            "吞了，别找我要啊。",
        ],
        "spit": profile["lines"]["spit"],
        "too_big": ["这文件也太大了吧，我嘴小！", "想撑死我啊？"],
        "hungry": profile["lines"]["hungry"],
        "study": profile["lines"]["study"],
        "wake": profile["lines"]["wake"],
        "poke": profile["lines"]["poke"],
        "pat": profile["lines"]["pat"],
        "drag": profile["lines"]["drag"],
        "drop": profile["lines"]["drop"],
        "feed": profile["lines"]["feed"],
        "sleep": profile["lines"]["sleep"],
        "rage": profile["lines"]["rage"],
        "work": profile["lines"]["work"],
        "play": profile["lines"]["play"],
        "idle": profile["lines"]["idle"],
        "pat_all": ["好啦好啦，都要摸是吧。", "排队排队，一个一个来。"],
    }
    config = {
        "name": profile["name"],
        "slug": profile["slug"],
        "subtitle": profile["subtitle"],
        "order": profile["order"],
        "scale": profile["scale"],
        "temper": profile["temper"],
        "accent": profile["accent"],
        "canvas": [DESIGN_W, DESIGN_H],
        "head_rect": HEAD_RECT,
        "body_rect": BODY_RECT,
        "mouth": MOUTH_FRACTION,
        "layers": {
            "body": "body.png",
            "walk": "body_walk.png",
            "dangle": "body_dangle.png",
        },
        "poses": {
            "idle": "body.png",
            "sit": "body.png",
            "walk_left": "body_walk.png",
            "walk_right": "body_walk.png",
            "drag": "body_dangle.png",
        },
        "parts": {name: f"parts/{name}.png" for name in RIG_PARTS},
        "rig": {"pivots": {name: list(pivot) for name, pivot in RIG_PIVOTS.items()}},
        "expressions": {name: f"heads/{name}.png" for name in EXPRESSIONS},
        "mount_points": {
            name: point.to_mapping()
            for name, point in default_mount_points(
                tuple(HEAD_RECT), tuple(BODY_RECT), tuple(MOUTH_FRACTION)
            ).items()
        },
        "motion": MotionProfile().to_mapping(),
        "lines": base_lines,
        "starting_accessories": list(profile.get("starting_accessories", [])),
        "bust_mode": False,
        "posture": "stand",
        "system": profile["slug"] in {"xiaoman", "laowang", "linlin", "elaina"},
        "voice_gain": 0.8,
        "notes": "把同学的照片按同一张 360x540 画布抠图分层，替换本文件夹中的 PNG 即可。",
    }
    char_dir.mkdir(parents=True, exist_ok=True)
    (char_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# external item sprites (never drawn in code)
# ---------------------------------------------------------------------------


def load_item_catalog() -> dict:
    """Load the external wardrobe/food catalogue and verify every PNG."""

    path = ITEMS / "catalog.json"
    if not path.is_file():
        raise SystemExit(
            f"缺少素材目录：{path}\n"
            "装扮和食物现在完全由外部 PNG + catalog.json 描述；"
            "请把独立精灵放回 assets/items/ 再运行。"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    missing: list[str] = []
    for group in ("items", "foods"):
        for raw in data.get(group, []):
            if not isinstance(raw, dict):
                continue
            relative = raw.get("file", "")
            if relative and not (ITEMS / str(relative)).is_file():
                missing.append(str(relative))
    for raw in data.get("props", {}).values():
        if isinstance(raw, dict) and raw.get("file") and not (ITEMS / str(raw["file"])).is_file():
            missing.append(str(raw["file"]))
    if missing:
        raise SystemExit(f"以下道具 PNG 缺失：{', '.join(sorted(set(missing)))}")
    return data


def verify_items() -> dict:
    """Items are read-only external art; this script never redraws them."""

    catalog = load_item_catalog()
    print(
        f"      {len(catalog.get('items', []))} wardrobe sprites, "
        f"{len(catalog.get('foods', []))} food sprites, "
        f"{len(catalog.get('props', {}))} props (external PNG, untouched)"
    )
    return catalog


def _character_mounts(slug: str) -> dict[str, MountPoint]:
    defaults = default_mount_points(
        tuple(HEAD_RECT), tuple(BODY_RECT), tuple(MOUTH_FRACTION)
    )
    path = CHARS / slug / "config.json"
    if not path.is_file():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    return normalise_mount_points(raw.get("mount_points"), defaults)


def _composite_mounted(
    base: Image.Image,
    sprite: Image.Image,
    mount: MountPoint,
    *,
    fit: float = 1.0,
    offset: tuple[float, float] = (0.0, 0.0),
) -> Image.Image:
    """Composite an external PNG at its socket (Pillow version of draw_mounted)."""

    left, top, width, height = mount_rect(
        mount,
        (DESIGN_W, DESIGN_H),
        sprite.size,
        fit=fit,
        offset=offset,
    )
    factor = base.width / DESIGN_W
    target = (
        max(1, round(width * factor)),
        max(1, round(height * factor)),
    )
    scaled = sprite.resize(target, Image.Resampling.LANCZOS)
    out = base.copy()
    out.alpha_composite(scaled, (round(left * factor), round(top * factor)))
    return out


# ---------------------------------------------------------------------------
# previews
# ---------------------------------------------------------------------------


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
    ):
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                pass
    return ImageFont.load_default()


def build_preview_sheet() -> None:
    width, height = 1600, 1010
    bg = Image.new("RGBA", (width, height), "#F7F1E7")
    d = ImageDraw.Draw(bg)
    # pastel blobs
    d.ellipse((-180, -220, 620, 560), fill="#E8DDF7")
    d.ellipse((1080, -150, 1780, 500), fill="#FBE0D3")
    d.ellipse((380, 700, 1240, 1190), fill="#DCEFE6")
    d.rounded_rectangle((45, 42, width - 45, height - 42), radius=34, outline="#D8C8B5", width=3)
    title_font = _font(68)
    sub_font = _font(26)
    name_font = _font(30)
    small_font = _font(23)
    d.text((85, 68), "桌角同学", font=title_font, fill="#3C3442")
    d.text((88, 148), "Deskling · Desktop Pet", font=sub_font, fill="#8A7562")
    d.text((88, 188), "宿舍同学纸片人分身 · 可以拎、可以喂、可以惹毛", font=small_font, fill="#8A7562")

    catalog = load_item_catalog()
    item_meta = {
        str(raw.get("id")): raw
        for raw in catalog.get("items", [])
        if isinstance(raw, dict)
    }
    card_w = 286
    start_x = 78
    gap = 18
    for i, profile in enumerate(PROFILES):
        body = Image.open(CHARS / profile["slug"] / "body.png").convert("RGBA")
        head_path = CHARS / profile["slug"] / "heads" / "happy.png"
        if not head_path.is_file():
            # Imported/single-layer characters may not ship every expression.
            head_path = CHARS / profile["slug"] / "head.png"
        if not head_path.is_file():
            head_path = CHARS / profile["slug"] / "heads" / "normal.png"
        head = (
            Image.open(head_path).convert("RGBA")
            if head_path.is_file()
            else Image.new("RGBA", body.size, (0, 0, 0, 0))
        )
        sprite = Image.alpha_composite(body, head)
        mounts = _character_mounts(profile["slug"])
        for accessory_id in profile.get("starting_accessories", []):
            raw = item_meta.get(accessory_id)
            if raw is None:
                continue
            accessory = ITEMS / str(raw.get("file", f"{accessory_id}.png"))
            if not accessory.is_file():
                continue
            source = Image.open(accessory).convert("RGBA")
            mount_name = str(raw.get("mount", "head_top"))
            if mount_name == "head":
                mount_name = "head_top"
            mount = mounts.get(mount_name) or next(iter(mounts.values()))
            sprite = _composite_mounted(
                sprite,
                source,
                mount,
                fit=float(raw.get("fit", 1.0)),
                offset=tuple(raw.get("offset", (0.0, 0.0))),
            )
        sprite.thumbnail((250, 390), Image.Resampling.LANCZOS)
        x = start_x + i * (card_w + gap)
        y = 238
        card_h = 650
        d.rounded_rectangle((x, y, x + card_w, y + card_h), radius=28, fill="#FFFDF8", outline="#E4D7C7", width=2)
        d.rounded_rectangle((x + 18, y + 17, x + card_w - 18, y + 60), radius=15, fill=profile["accent"])
        d.ellipse((x + 28, y + 28, x + 50, y + 50), fill="#FFFDF8")
        d.text((x + 60, y + 25), profile["name"], font=name_font, fill="#FFFFFF")
        d.text((x + 22, y + 68), profile["subtitle"], font=small_font, fill="#8A7562")
        # stable drop shadow
        shadow = Image.new("RGBA", sprite.size, (0, 0, 0, 0))
        alpha = sprite.getchannel("A")
        shadow.putalpha(alpha.point(lambda v: int(v * 0.20)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(8))
        bg.alpha_composite(shadow, (x + (card_w - sprite.width) // 2, y + 154 + 5))
        bg.alpha_composite(sprite, (x + (card_w - sprite.width) // 2, y + 154))
        d = ImageDraw.Draw(bg)
        d.ellipse((x + 54, y + 570, x + card_w - 54, y + 590), fill=profile["accent"] + "20")
        quote = profile["lines"]["idle"][0]
        if len(quote) > 13:
            quote = quote[:13] + "…"
        d.text((x + 18, y + 600), f"“{quote}”", font=small_font, fill="#6E6054")

    footer = _font(21)
    d.text((90, height - 89), "原创占位角色 · 把 characters/<角色>/ 里的图层换成同学照片即可", font=footer, fill="#8A7562")
    d.text((width - 310, height - 89), "Python + PyQt6", font=footer, fill="#8A7562")
    SHOTS.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(SHOTS / "characters.png", optimize=True)


def build_app_icon() -> None:
    """Text-free app icon: a classmate peeking over a folded paper note."""

    size = 1024
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # deep-violet rounded background
    gradient = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    top = (132, 111, 255)
    bottom = (64, 43, 146)
    for y in range(size):
        t = (y / (size - 1)) ** 0.86
        col = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        gd.line([(0, y), (size, y)], fill=col + (255,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((30, 30, size - 30, size - 30), radius=224, fill=255)
    icon.alpha_composite(gradient)
    icon.putalpha(mask)

    # soft pastel glow behind the paper
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gl = ImageDraw.Draw(glow)
    gl.ellipse((-240, 410, 620, 1230), fill=(255, 196, 153, 72))
    gl.ellipse((570, -260, 1310, 480), fill=(180, 225, 255, 50))
    glow = glow.filter(ImageFilter.GaussianBlur(72))
    icon.alpha_composite(glow)

    d = ImageDraw.Draw(icon)
    for x, y, r, a in ((155, 180, 4, 120), (870, 160, 3, 95), (920, 500, 5, 80), (100, 680, 3, 90)):
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, a))

    # chibi head, cropped to its alpha bounds so it reads well at small sizes
    head_path = CHARS / "azhai" / "heads" / "normal.png"
    x0, y0, x1, y1 = alpha_bbox(head_path, pad=2)
    head = Image.open(head_path).convert("RGBA").crop((x0, y0, x1, y1))
    head = head.resize((632, max(1, round(head.height * 632 / head.width))), Image.Resampling.LANCZOS)
    hx, hy = (size - head.width) // 2, 74
    silhouette = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    silhouette.alpha_composite(
        Image.new("RGBA", head.size, (26, 16, 46, 105)),
        (hx + 10, hy + 24),
    )
    silhouette = silhouette.filter(ImageFilter.GaussianBlur(22))
    icon.alpha_composite(silhouette)
    icon.alpha_composite(head, (hx, hy))

    # folded cream note in front, at a playful angle
    paper = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pd = ImageDraw.Draw(paper)
    left, top_y, right, bottom_y = 92, 548, 932, 916
    pd.rounded_rectangle(
        (left, top_y, right, bottom_y),
        radius=62,
        fill=(255, 248, 233, 255),
        outline=(55, 42, 62, 255),
        width=10,
    )
    fold = 134
    pd.polygon(
        [(right - fold, top_y), (right, top_y), (right, top_y + fold)],
        fill=(246, 207, 146, 255),
        outline=(55, 42, 62, 255),
    )
    pd.line(
        [(right - fold, top_y), (right, top_y + fold), (right - fold, top_y + fold)],
        fill=(55, 42, 62, 180),
        width=5,
        joint="curve",
    )
    pd.rounded_rectangle((156, 704, 428, 716), radius=6, fill=(196, 184, 214, 210))
    pd.rounded_rectangle((156, 739, 350, 751), radius=6, fill=(215, 203, 226, 165))
    for x, y, r, col in (
        (786, 764, 14, (255, 183, 104)),
        (825, 792, 8, (118, 202, 174)),
        (779, 810, 7, (255, 210, 108)),
    ):
        pd.ellipse((x - r, y - r, x + r, y + r), fill=col + (255,))
    pd.arc((694, 576, 772, 692), 270, 90, fill=(255, 206, 96, 255), width=10)
    pd.arc((718, 604, 744, 684), 270, 90, fill=(255, 206, 96, 255), width=6)

    paper_shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_alpha = paper.getchannel("A").point(lambda v: int(v * 0.30))
    shadow_layer = Image.new("RGBA", paper.size, (20, 10, 34, 255))
    shadow_layer.putalpha(shadow_alpha)
    paper_shadow.alpha_composite(shadow_layer, (8, 26))
    paper_shadow = paper_shadow.filter(ImageFilter.GaussianBlur(22))
    icon.alpha_composite(paper_shadow)
    paper = paper.rotate(-3.2, resample=Image.Resampling.BICUBIC, center=(size / 2, 740))
    icon.alpha_composite(paper)

    ad = ImageDraw.Draw(icon)
    ad.polygon(
        [(142, 216), (155, 255), (194, 268), (155, 281), (142, 320), (129, 281), (90, 268), (129, 255)],
        fill=(255, 222, 140, 235),
    )
    ad.ellipse((882, 292, 906, 316), fill=(137, 225, 195, 225))
    ad.ellipse((124, 364, 140, 380), fill=(255, 255, 255, 150))

    border = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        (40, 40, size - 40, size - 40),
        radius=214,
        outline=(255, 255, 255, 60),
        width=4,
    )
    icon.alpha_composite(border)
    final = icon.resize((512, 512), Image.Resampling.LANCZOS)
    final.save(ASSETS / "icon.png", "PNG", optimize=True)
    # BMP frames are the most compatible format for Windows Explorer shortcut
    # icons.  The PNG-compressed variant showed up as a generic blank page on
    # this machine until the icon was copied outside the D: workspace.
    final.save(
        ASSETS / "deskling.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        bitmap_format="bmp",
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Deskling placeholder art")
    parser.add_argument("--skip-sounds", action="store_true", help="do not regenerate WAV files")
    parser.add_argument("--skip-preview", action="store_true", help="do not regenerate screenshots")
    args = parser.parse_args()

    ASSETS.mkdir(parents=True, exist_ok=True)
    ITEMS.mkdir(parents=True, exist_ok=True)
    CHARS.mkdir(parents=True, exist_ok=True)

    print("[1/6] rendering character layers ...")
    build_all_characters(CHARS)

    print("[2/6] checking external wardrobe, food and prop sprites ...")
    verify_items()

    print("[3/6] writing character configs ...")
    for profile in PROFILES:
        write_character_config(profile, CHARS / profile["slug"])

    print("[4/6] composing sounds ...")
    if not args.skip_sounds:
        build_sounds()

    print("[5/6] drawing the app icon and preview ...")
    build_app_icon()
    if not args.skip_preview:
        build_preview_sheet()

    print("[6/6] done.")
    print(f"  characters: {CHARS}")
    print(f"  assets:     {ASSETS}")
    print(f"  preview:    {SHOTS / 'characters.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
