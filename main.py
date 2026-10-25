"""Deskling · 桌角同学 — launcher.

Double-click start.bat, or run:
    python main.py
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

try:
    from PyQt6.QtCore import QLockFile, Qt
    from PyQt6.QtGui import QGuiApplication, QIcon
    from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
except ImportError as exc:  # pragma: no cover - friendly first-run error
    print("缺少 PyQt6，请先运行：python -m pip install -r requirements.txt", file=sys.stderr)
    print(f"详细错误：{exc}", file=sys.stderr)
    raise SystemExit(1) from exc

from petapp import __app_name__, __version__
from petapp.config import Catalog, Settings, load_characters
from petapp.manager import PetManager
from petapp.paths import (
    CATALOG_FILE,
    CHARACTERS_DIR,
    ICON_FILE,
    ITEMS_DIR,
    LOCK_FILE,
    LOG_FILE,
    SETTINGS_FILE,
    ensure_characters_dir,
    ensure_data_dir,
)
from petapp.theme import apply_app_style
from petapp.tray import TrayController
from petapp import win32

log = logging.getLogger("deskling")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="桌角同学 Deskling 桌宠")
    parser.add_argument("--debug", action="store_true", help="在控制台输出调试日志")
    parser.add_argument(
        "--allow-multiple",
        action="store_true",
        help="允许同时启动多个程序实例（默认只允许一个）",
    )
    parser.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    parser.add_argument(
        "--quit-after",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def configure_logging(debug: bool) -> None:
    ensure_data_dir()
    handlers: list[logging.Handler] = []
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    handlers.append(file_handler)
    if debug and sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
        handlers.append(console)
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=handlers)


def install_excepthook(app: QApplication) -> None:
    original = sys.excepthook

    def hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            original(exc_type, exc_value, exc_tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.critical("未捕获异常\n%s", text)
        try:
            QMessageBox.critical(
                None,
                "桌角同学出现了一点问题",
                "程序遇到一个未预料的错误，但可能还在运行。\n\n"
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"完整日志：{LOG_FILE}",
            )
        except Exception:
            pass

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    configure_logging(args.debug)
    log.info("启动 %s %s", __app_name__, __version__)

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1] + list(argv or []))
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Deskling")
    app.setApplicationDisplayName("桌角同学")
    app.setOrganizationName("Deskling")
    apply_app_style(app)
    win32.set_app_user_model_id()
    if ICON_FILE.is_file():
        app.setWindowIcon(QIcon(str(ICON_FILE)))
    install_excepthook(app)

    lock: QLockFile | None = None
    if not args.allow_multiple:
        lock = QLockFile(str(LOCK_FILE))
        lock.setStaleLockTime(30_000)
        if not lock.tryLock(120):
            log.info("已有实例正在运行")
            QMessageBox.information(
                None,
                "桌角同学已经在桌面上了",
                "它已经在运行啦。\n\n看看屏幕右下角的系统托盘，或者桌面上有没有一个纸片人。",
            )
            return 0

    try:
        if not CATALOG_FILE.is_file():
            QMessageBox.critical(
                None,
                "素材不完整",
                f"没有找到素材目录：\n{CATALOG_FILE}\n\n"
                "请确认整个 DesktopPet 文件夹被完整解压，或运行 "
                "python tools/generate_assets.py 重新生成占位素材。",
            )
            return 1
        try:
            catalog = Catalog.load(ITEMS_DIR)
        except Exception as exc:
            log.exception("素材目录加载失败")
            QMessageBox.critical(None, "素材加载失败", f"{exc}\n\n素材目录：{ITEMS_DIR}")
            return 1
        characters = load_characters(ensure_characters_dir())
        if not characters:
            QMessageBox.critical(
                None,
                "没有找到可用同学",
                f"characters 文件夹里没有可用的角色。\n\n"
                f"请检查：{CHARACTERS_DIR}\n"
                "每个角色至少需要 config.json 和 body.png。",
            )
            return 1

        settings = Settings.load(SETTINGS_FILE)
        first_run = settings.first_run
        manager = PetManager(app, characters, catalog, settings, SETTINGS_FILE)
        tray = TrayController(manager)
        manager.attach_tray(tray)
        tray.show()
        window = manager.start()
        if window is None:
            QMessageBox.warning(
                None,
                "桌宠没有出现",
                "角色加载成功，但桌宠窗口没有创建出来。\n"
                f"请查看日志：{LOG_FILE}",
            )
        elif first_run and tray.icon.isVisible():
            tray.icon.showMessage(
                "桌角同学已上线",
                "左键点托盘图标可以显示/收起，右键有更多玩法。\n"
                "右键桌宠可以投喂、换装，拖一个文件给它也行。",
                QSystemTrayIcon.MessageIcon.Information,
                6500,
            )
        app.aboutToQuit.connect(manager.shutdown)
        if args.quit_after > 0:
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(int(args.quit_after * 1000), app.quit)
        code = app.exec()
        log.info("退出，代码 %s", code)
        return int(code)
    finally:
        if lock is not None:
            lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
