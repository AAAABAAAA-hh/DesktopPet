"""Small, dependency-free Windows integration helpers.

Only window styles and foreground-process information are touched here.
No information leaves the computer.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .window import PetWindow

log = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

    GWL_EXSTYLE = -20
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_NOACTIVATE = 0x08000000
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020
    HWND_TOPMOST = wintypes.HWND(-1)

    # DWM window attributes. Windows 11 decorates every top-level window with
    # a rounded corner, a hairline border and a soft drop shadow unless it is
    # told not to; on a per-pixel transparent pet window that decoration is
    # exactly the "dark rounded slab" people notice behind the character.
    DWMWA_TRANSITIONS_FORCEDISABLED = 3
    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWA_BORDER_COLOR = 34
    DWMWA_SYSTEMBACKDROP_TYPE = 38
    DWMWCP_DONOTROUND = 1
    DWMSBT_NONE = 1
    DWMWA_COLOR_NONE = 0xFFFFFFFE

    _dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

    try:
        _get_long = _user32.GetWindowLongPtrW
        _set_long = _user32.SetWindowLongPtrW
        _get_long.restype = ctypes.c_ssize_t
        _get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        _set_long.restype = ctypes.c_ssize_t
        _set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    except AttributeError:  # 32-bit Python still has the short forms
        _get_long = _user32.GetWindowLongW
        _set_long = _user32.SetWindowLongW
        _get_long.restype = ctypes.c_long
        _get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        _set_long.restype = ctypes.c_long
        _set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]

    _user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short

    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _hwnd_value(hwnd: int) -> int:
    try:
        return int(hwnd)
    except (TypeError, ValueError):
        return 0


def style_pet_window(hwnd: int, no_activate: bool = True) -> None:
    """Hide from Alt+Tab and (optionally) stop clicks from stealing focus."""

    if not IS_WINDOWS or not hwnd:
        return
    try:
        style = _get_long(wintypes.HWND(hwnd), GWL_EXSTYLE)
        style |= WS_EX_TOOLWINDOW
        style &= ~WS_EX_APPWINDOW
        if no_activate:
            style |= WS_EX_NOACTIVATE
        _set_long(wintypes.HWND(hwnd), GWL_EXSTYLE, style)
    except Exception as exc:
        log.debug("style_pet_window failed: %s", exc)
        return
    strip_window_frame(hwnd)
    place_topmost(hwnd, activate=False)


def strip_window_frame(hwnd: int) -> bool:
    """Remove every piece of OS window decoration around a transparent pet.

    Windows 11 draws a rounded corner, a 1px accent border and a soft shadow
    around top-level windows.  On top of a dark wallpaper the shadow reads as
    a semi-transparent dark plate and the border as a rounded rectangle around
    the character.  This asks DWM to stop decorating the window, so only the
    sprite itself remains on screen.

    Returns True when at least one attribute was accepted by the system.
    """

    if not IS_WINDOWS or not hwnd:
        return False
    handle = wintypes.HWND(hwnd)
    applied = False
    attributes = (
        (DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND),
        (DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE),
        (DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE),
        (DWMWA_TRANSITIONS_FORCEDISABLED, 1),
    )
    for attribute, value in attributes:
        try:
            data = ctypes.c_int(value)
            result = _dwmapi.DwmSetWindowAttribute(
                handle, wintypes.DWORD(attribute), ctypes.byref(data), ctypes.sizeof(data)
            )
        except Exception:  # pragma: no cover - depends on the OS build
            log.debug("DwmSetWindowAttribute(%s) failed", attribute, exc_info=True)
            continue
        if result == 0:
            applied = True
        else:
            log.debug("DwmSetWindowAttribute(%s) -> 0x%08X", attribute, result & 0xFFFFFFFF)
    return applied


def set_click_through(hwnd: int, enabled: bool) -> bool:
    """Toggle WS_EX_TRANSPARENT, preserving all other window styles."""

    if not IS_WINDOWS or not hwnd:
        return False
    try:
        hwnd_value = wintypes.HWND(hwnd)
        style = _get_long(hwnd_value, GWL_EXSTYLE)
        if enabled:
            new_style = style | WS_EX_TRANSPARENT
        else:
            new_style = style & ~WS_EX_TRANSPARENT
        if new_style == style:
            return True
        _set_long(hwnd_value, GWL_EXSTYLE, new_style)
        return True
    except Exception as exc:
        log.debug("set_click_through failed: %s", exc)
        return False


def place_topmost(hwnd: int, activate: bool = False) -> None:
    if not IS_WINDOWS or not hwnd:
        return
    flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    if not activate:
        flags |= SWP_NOACTIVATE
    try:
        _user32.SetWindowPos(wintypes.HWND(hwnd), HWND_TOPMOST, 0, 0, 0, 0, flags)
    except Exception as exc:
        log.debug("place_topmost failed: %s", exc)


def escape_pressed() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(_user32.GetAsyncKeyState(0x1B) & 0x8000)
    except Exception:
        return False


def foreground_info() -> tuple[str, str]:
    """Return (executable basename, window title) of the active window."""

    if not IS_WINDOWS:
        return ("", "")
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return ("", "")
    try:
        title_length = _user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(max(1, title_length + 1))
        _user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        title = title_buffer.value.strip()

        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        if pid.value:
            handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if handle:
                try:
                    size = wintypes.DWORD(1024)
                    buffer = ctypes.create_unicode_buffer(size.value)
                    if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                        exe = Path(buffer.value).name.lower()
                finally:
                    _kernel32.CloseHandle(handle)
        return (exe, title)
    except Exception as exc:
        log.debug("foreground_info failed: %s", exc)
        return ("", "")


def set_app_user_model_id(app_id: str = "Deskling.DesktopPet") -> None:
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def pet_window_handle(window: "PetWindow") -> int:
    """Safely retrieve the native HWND for a Qt widget."""

    try:
        return _hwnd_value(window.winId())
    except Exception:
        return 0
