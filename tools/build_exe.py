"""Build a Windows executable for Deskling with PyInstaller.

Usage (from the project folder):

    python -m pip install pyinstaller
    python tools/build_exe.py            # folder build (recommended)
    python tools/build_exe.py --onefile  # single-file build

A folder build (``dist/Deskling/``) is recommended: it starts faster and does
not need to unpack anything into ``%TEMP%``, which some machines block for
unsigned executables.  Send the whole ``dist/Deskling`` folder (zipped).

Writable state always goes to ``%APPDATA%\\Deskling`` (see ``petapp/paths.py``),
and the bundled ``characters`` folder is copied there on first run, so the
exe folder can stay read-only.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "Deskling"
DISPLAY_NAME = "桌角同学"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打包桌角同学")
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="打成单个 exe（需要可写的 %%TEMP%%，启动更慢）",
    )
    args = parser.parse_args(argv)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller，请先运行：python -m pip install pyinstaller")
        return 1

    icon = ROOT / "assets" / "deskling.ico"
    if not icon.is_file():
        icon = ROOT / "assets" / "icon.png"
    separator = os.pathsep
    mode = "--onefile" if args.onefile else "--onedir"
    args_list = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        mode,
        "--windowed",
        "--noupx",
        "--name",
        APP_NAME,
        "--icon",
        str(icon),
        "--add-data",
        f"{ROOT / 'assets'}{separator}assets",
        "--add-data",
        f"{ROOT / 'characters'}{separator}characters",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT / "build"),
        str(ROOT / "main.py"),
    ]
    print("PyInstaller:", " ".join(args_list))
    completed = subprocess.run(args_list, cwd=ROOT)
    if completed.returncode != 0:
        print(f"打包失败，返回码 {completed.returncode}")
        return completed.returncode

    if args.onefile:
        exe = ROOT / "dist" / f"{APP_NAME}.exe"
        result = exe
    else:
        exe = ROOT / "dist" / APP_NAME / f"{APP_NAME}.exe"
        result = exe.parent
    if not exe.is_file():
        print(f"没有找到打包结果：{exe}")
        return 1
    if args.onefile:
        friendly = exe.with_name(f"{DISPLAY_NAME}.exe")
        try:
            shutil.copy2(exe, friendly)
            result = friendly
        except OSError:
            pass
    size = (
        result.stat().st_size
        if result.is_file()
        else sum(p.stat().st_size for p in result.rglob("*") if p.is_file())
    )
    print(f"完成：{result} ({size / 1024 / 1024:.1f} MB)")
    print("文件夹版请把整个 dist/Deskling 目录打成 zip 再发给别人。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
