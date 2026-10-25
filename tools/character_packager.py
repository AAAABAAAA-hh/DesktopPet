#!/usr/bin/env python3
"""Universal Deskling character packager.

Turn any local image into a complete, animation-ready character folder:

    python tools/character_packager.py path/to/art.png
    python tools/character_packager.py photo.jpg --name 我的同学 --scale 0.8

The command and the in-app “➕ 导入新角色” button both call
:func:`petapp.packager.package_character`, so every character shares exactly
the same 720×1080 layer contract, neck pivot, click boxes and motion profile.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from petapp.config import load_characters  # noqa: E402
from petapp.packager import package_character  # noqa: E402


def _parse_motion(value: str | None) -> dict:
    if not value:
        return {}
    if Path(value).is_file():
        payload = json.loads(Path(value).read_text(encoding="utf-8-sig"))
    else:
        payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("--motion 必须是 JSON 对象")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="把任意立绘/照片打包成 Deskling 通用角色（头/身体分层 + config.json）"
    )
    parser.add_argument("source", type=Path, help="输入图片：PNG / JPG / WEBP…")
    parser.add_argument(
        "--characters-dir",
        type=Path,
        default=ROOT / "characters",
        help="角色根目录（默认 characters/）",
    )
    parser.add_argument("--name", help="显示名；默认取文件名")
    parser.add_argument("--slug", help="文件夹 / 内部 ID；默认由名字生成")
    parser.add_argument("--subtitle", default="自定义导入角色", help="人物卡称号")
    parser.add_argument(
        "--posture",
        choices=("stand", "sit"),
        default=None,
        help="姿态：stand 站姿（会走动）/ sit 坐姿趴桌（固定原地）",
    )
    parser.add_argument(
        "--big-head",
        dest="big_head",
        action="store_true",
        default=None,
        help="强制 1.4x 大头构图（真人/长身立绘可自动启用）",
    )
    parser.add_argument(
        "--no-big-head",
        dest="big_head",
        action="store_false",
        help="关闭大头构图，保持原始比例",
    )
    parser.add_argument(
        "--head-scale",
        type=float,
        default=1.4,
        help="大头构图的头部缩放倍率，默认 1.4",
    )
    parser.add_argument("--order", type=float, default=0.0, help="列表排序权重")
    parser.add_argument("--scale", type=float, default=0.8, help="默认显示比例 0.5~1.35")
    parser.add_argument("--temper", type=float, default=1.0, help="脾气倍率 0.2~2.5")
    parser.add_argument("--accent", help="气泡主题色，例如 #9B7BD6")
    parser.add_argument("--rage-threshold", type=float, default=99.5, help="暴走怒气阈值 1~100")
    parser.add_argument(
        "--motion",
        help="动作参数 JSON 字符串或 JSON 文件路径（见 README 的 motion 段）",
    )
    parser.add_argument(
        "--no-expressions",
        action="store_true",
        help="兼容旧命令（已废弃：导入不再自动绘制任何表情图层）",
    )
    parser.add_argument("--json", action="store_true", help="只输出生成的 config.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Deskling Character Packager")
    source = args.source if args.source.is_absolute() else Path.cwd() / args.source
    characters_dir = (
        args.characters_dir
        if args.characters_dir.is_absolute()
        else (Path.cwd() / args.characters_dir)
    )
    characters_dir.mkdir(parents=True, exist_ok=True)
    existing = load_characters(characters_dir)
    try:
        character = package_character(
            source,
            characters_dir,
            existing_slugs={c.slug for c in existing},
            existing_names={c.name for c in existing},
            order=max((c.order for c in existing), default=0.0),
            name=args.name,
            slug=args.slug,
            subtitle=args.subtitle,
            posture=args.posture,
            big_head=args.big_head,
            head_scale=args.head_scale,
            scale=args.scale,
            temper=args.temper,
            accent=args.accent,
            motion=_parse_motion(args.motion),
            rage_threshold=args.rage_threshold,
            generate_expressions=not args.no_expressions,
        )
    except Exception as exc:
        print(f"[packager] 失败：{exc}", file=sys.stderr)
        return 2
    config = json.loads((character.folder / "config.json").read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0
    print(f"[packager] 完成：{character.folder}")
    print(f"  name       {character.name} ({character.slug})")
    print(f"  canvas     {config['canvas'][0]}x{config['canvas'][1]} (export 720x1080)")
    print(f"  head       {character.folder / 'head.png'}")
    print(f"  body       {character.folder / 'body.png'}")
    print(f"  skeleton   {character.folder / 'skeleton.json'}")
    print(f"  expressions {', '.join(sorted(config['expressions'])) or '-'}")
    print(f"  pivot      {config['rig']['pivots']['head']}")
    print(f"  accent     {config['accent']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
