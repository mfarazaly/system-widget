# -*- coding: utf-8 -*-
"""
SystemWidget - a tiny always-on-top system monitor for Windows.

Shows CPU, RAM, GPU, network throughput and estimated system power.
Rows, theme and other options live in the right-click menu.

Double-click to run (uses pythonw.exe, so there is no console window).
Right-click for options.  Ctrl+Alt+W hides / shows the widget.

Requires: psutil   (pip install psutil)
GPU stats need an NVIDIA GPU (NVML, with nvidia-smi as a fallback).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from collections import deque
from dataclasses import dataclass
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - only on a broken install
    ctypes.windll.user32.MessageBoxW(
        None,
        "This widget needs psutil.\n\nOpen a terminal and run:\n\n    pip install psutil",
        "System Widget",
        0x10,
    )
    sys.exit(1)

# --------------------------------------------------------------- win32 --
# Pointer arguments need real prototypes: passing HWND_TOPMOST (-1) as a
# plain Python int lets ctypes truncate it, so the call fails with
# ERROR_INVALID_WINDOW_HANDLE instead of moving the window.
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SetWindowPos.argtypes = [
    wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT,
]
_user32.SetWindowPos.restype = ctypes.c_bool
_user32.GetParent.argtypes = [wt.HWND]
_user32.GetParent.restype = wt.HWND
_user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
_user32.SetWindowLongW.restype = ctypes.c_long
_user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
_user32.ShowWindow.restype = ctypes.c_bool
_user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
_user32.FindWindowW.restype = wt.HWND
_user32.GetTopWindow.argtypes = [wt.HWND]
_user32.GetTopWindow.restype = wt.HWND
_user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
_user32.GetWindow.restype = wt.HWND
_user32.GetForegroundWindow.restype = wt.HWND
_user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
_user32.GetWindowRect.restype = ctypes.c_bool
_user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_user32.GetWindowThreadProcessId.restype = wt.DWORD
_user32.IsWindowVisible.argtypes = [wt.HWND]
_user32.IsWindowVisible.restype = ctypes.c_bool
_user32.IsIconic.argtypes = [wt.HWND]
_user32.IsIconic.restype = ctypes.c_bool

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOREDRAW = 0x0008
SWP_NOACTIVATE = 0x0010
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
GW_HWNDNEXT = 2
DWMWA_CLOAKED = 14

# Shell/UI windows that belong above the widget even though they are topmost.
# Popup menus ("#32768") and tooltips are included so the widget never covers
# a tray or app menu when it is parked in the corner.
SHELL_ABOVE = {
    "#32768",
    "tooltips_class32",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow",
    "TopLevelWindowForOverflowXamlIsland",
    "MultitaskingViewFrame",
    "TaskSwitcherWnd",
}

try:
    _dwmapi = ctypes.WinDLL("dwmapi")
    _dwmapi.DwmGetWindowAttribute.argtypes = [
        wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD,
    ]
    _dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
except OSError:  # pragma: no cover - every supported Windows has dwmapi
    _dwmapi = None


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", wt.RECT),
        ("rcWork", wt.RECT),
        ("dwFlags", wt.DWORD),
    ]


_user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
_user32.MonitorFromWindow.restype = wt.HANDLE
_user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(_MONITORINFO)]
_user32.GetMonitorInfoW.restype = ctypes.c_bool
try:                                    # Windows 10 1607 and later
    _user32.GetDpiForWindow.argtypes = [wt.HWND]
    _user32.GetDpiForWindow.restype = wt.UINT
except AttributeError:                  # pragma: no cover
    pass

MONITOR_DEFAULTTONEAREST = 2

# SHQueryUserNotificationState: the shell's own idea of what owns the screen.
QUNS_BUSY = 2                           # a fullscreen app (or presentation)
QUNS_RUNNING_D3D_FULL_SCREEN = 3        # exclusive-mode Direct3D
QUNS_ACCEPTS_NOTIFICATIONS = 5          # normal desktop / borderless games

try:
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _shell32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
    _shell32.SHQueryUserNotificationState.restype = ctypes.c_long
except OSError:                         # pragma: no cover
    _shell32 = None


def fullscreen_app_running() -> bool:
    """True while a fullscreen app (exclusive game, presentation) owns the screen.

    Nothing can be drawn over exclusive fullscreen, and poking the z-order
    while a game holds the display makes some games drop out of fullscreen,
    so the widget steps aside until the state goes back to normal.
    """
    if _shell32 is None:
        return False
    state = ctypes.c_int(0)
    if _shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
        return False
    return state.value in (QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN)


def _is_cloaked(window: int) -> bool:
    """True for windows DWM hides without unsetting WS_VISIBLE.

    Suspended UWP apps stay "visible" in the z-order but are not drawn, so
    they would otherwise look like something covering the widget.
    """
    if _dwmapi is None:
        return False
    value = ctypes.c_int(0)
    result = _dwmapi.DwmGetWindowAttribute(
        window, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)
    )
    return result == 0 and bool(value.value)


# --------------------------------------------------------------------------- #
#  Configuration
# --------------------------------------------------------------------------- #

APP_NAME = "SystemWidget"
VERSION = "1.2.9"
CREATED = "20 October 2026"
DEVELOPER = "M Faraz Ali"
EMAIL = "mfarazaly@gmail.com"
ABOUT_TEXT = (
    "I\u2019m a technology enthusiast and creative professional passionate about "
    "AI, software development, game development, 3D design, and digital content "
    "creation. I enjoy learning new technologies, solving problems, and turning "
    "creative ideas into practical projects."
)

HOTKEY_MODIFIERS = ("ctrl", "alt")      # ctrl / alt / shift / win
HOTKEY_KEY = "w"                        # hide / show
TOPMOST_KEY = "t"                       # toggle always-on-top
LOCK_KEY = "l"                          # lock / unlock the mouse

# Base size at 100% display scaling
BASE_W = 262
ROW_H = 44                              # height of one metric row
HEADER_H = 50                           # header + separator
BOTTOM_PAD = 16
BAR_OFFSET = 25                         # bar top, relative to the row
BAR_H = 7

COL_BG = "#0c0e13"
COL_KEY = "#010101"                     # colour-keyed -> transparent corners
COL_BORDER = "#252b39"
COL_TRACK = "#1a2030"
COL_HEADER = "#69738a"
COL_LABEL = "#b9c2d4"
COL_DETAIL = "#5f697e"
COL_VALUE = "#f2f5fb"

# CPU model for the power estimate (Ryzen 7 7700 = 65 W TDP).
# Platform = motherboard, RAM, SSDs, fans, pump - not directly measurable.
CPU_TDP_W = 65
PLATFORM_W = 18


@dataclass(frozen=True)
class RowSpec:
    key: str
    label: str
    accent: str
    kind: str                           # percent | speed | watts
    menu_label: str = ""


ROWS = (
    RowSpec("cpu", "CPU", "#4c9aff", "percent", "CPU"),
    RowSpec("ram", "RAM", "#b07cff", "percent", "RAM"),
    RowSpec("gpu", "GPU", "#2dd4a7", "percent", "GPU"),
    RowSpec("temp", "TEMP", "#ff7a45", "temp", "Temperature"),
    RowSpec("net", "NET", "#f5a524", "speed", "Internet"),
    RowSpec("power", "POWER", "#ff5c8a", "watts", "Power"),
)
ROW_BY_KEY = {row.key: row for row in ROWS}
ALL_ROW_KEYS = [row.key for row in ROWS]

THEMES = ("card", "strip", "minimal", "rings")
THEME_LABELS = {
    "card": "Card (vertical)",
    "strip": "Horizontal bar",
    "minimal": "Minimal text",
    "rings": "Gauge rings",
}

SETTINGS_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULTS = {
    "x": None,
    "y": None,
    "corner_dx": None,      # gap to the bottom-right corner, kept per display
    "corner_dy": None,
    "opacity": 0.97,
    "topmost": True,
    "above_taskbar": True,
    "locked": False,
    "hide_in_games": False,     # Windows cannot tell borderless from exclusive
    "refresh": 1.0,
    "rows": list(ALL_ROW_KEYS),
    "theme": "card",
    "ui_scale": 1.0,
    "adapt_scale": True,        # shrink proportionally on smaller displays
    "scale_ref_w": None,        # display the chosen size belongs to
    "scale_ref_h": None,
    "cpu_tdp": CPU_TDP_W,
}

SCHEMA = 2                              # 2 = the Temperature row exists

UI_SCALE_MIN = 0.5
UI_SCALE_MAX = 1.5
OPACITY_MIN = 0.2

# The slider stops at 50 %, but a game at 640x480 needs to go lower to keep a
# readable fraction of the screen.  Below this the text stops being legible.
AUTO_SCALE_FLOOR = 0.4

VK_CODES = {chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)}
VK_CODES.update({chr(c): c for c in range(ord("0"), ord("9") + 1)})

MOD_FLAGS = {
    "alt": 0x0001,
    "ctrl": 0x0002,
    "shift": 0x0004,
    "win": 0x0008,
}


def load_settings() -> dict:
    data = dict(DEFAULTS)
    loaded: dict = {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8-sig") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            data.update({k: v for k, v in loaded.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass

    rows = [
        key for key in ALL_ROW_KEYS
        if key in (data.get("rows") or [])
    ]
    # Files written before the Temperature row existed get it switched on
    # once; from then on the schema stamp keeps a deliberate "off" in place.
    try:
        schema = int(loaded.get("schema") or 0)
    except (TypeError, ValueError):
        schema = 0
    if schema < SCHEMA and "temp" not in rows:
        rows = [key for key in ALL_ROW_KEYS if key in set(rows) | {"temp"}]
    data["rows"] = rows or list(ALL_ROW_KEYS)
    data["schema"] = SCHEMA
    if data.get("theme") not in THEMES:
        data["theme"] = "card"

    try:
        scale = float(data.get("ui_scale") or 1.0)
    except (TypeError, ValueError):
        scale = 1.0
    data["ui_scale"] = max(UI_SCALE_MIN, min(UI_SCALE_MAX, scale))

    try:
        opacity = float(data.get("opacity") or 1.0)
    except (TypeError, ValueError):
        opacity = 1.0
    data["opacity"] = max(OPACITY_MIN, min(1.0, opacity))
    return data


def save_settings(data: dict) -> None:
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        tmp.replace(SETTINGS_FILE)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
#  Autostart (HKCU ... \Run)
# --------------------------------------------------------------------------- #

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_command() -> str:
    """Command that starts this widget, for the Run registry key."""
    if getattr(sys, "frozen", False):        # running as a PyInstaller exe
        return f'"{Path(sys.executable).resolve()}"'

    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            exe = candidate
    return f'"{exe}" "{Path(__file__).resolve()}"'


def autostart_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
        return value.strip().lower() == _launch_command().strip().lower()
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(
                    key, APP_NAME, 0, winreg.REG_SZ, _launch_command()
                )
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
#  GPU sampling (NVIDIA: NVML in-process, nvidia-smi as a fallback)
# --------------------------------------------------------------------------- #

class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class GpuSampler:
    """Polls NVIDIA GPU stats on a worker thread and keeps the latest reading."""

    QUERY = "name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
    CREATE_NO_WINDOW = 0x08000000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict | None = None
        self._name: str | None = None
        self._interval = 1.0
        self._stop = threading.Event()
        self.available: bool | None = None
        self._nvml = None
        self._handle = None
        self._init_nvml()

    # ---------------------------------------------------------- backends --

    def _init_nvml(self) -> None:
        for dll in ("nvml.dll", r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll"):
            try:
                lib = ctypes.WinDLL(dll)
                if lib.nvmlInit_v2() != 0:
                    continue
                count = ctypes.c_uint()
                if lib.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0 or not count.value:
                    continue
                handle = ctypes.c_void_p()
                if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
                    continue
            except (OSError, AttributeError):
                continue

            self._nvml = lib
            self._handle = handle
            self._name = self._short_name(self._read_nvml_name())
            return

    def _read_nvml_name(self) -> str:
        buf = ctypes.create_string_buffer(96)
        try:
            if self._nvml.nvmlDeviceGetName(self._handle, buf, 96) != 0:
                return "GPU"
        except AttributeError:
            return "GPU"
        return buf.value.decode("utf-8", "replace")

    @staticmethod
    def _short_name(name: str) -> str:
        for prefix in ("NVIDIA GeForce ", "NVIDIA "):
            if name.startswith(prefix):
                return name[len(prefix):]
        return name

    def _sample_nvml(self) -> dict | None:
        lib, handle = self._nvml, self._handle
        util = _NvmlUtilization()
        mem = _NvmlMemory()
        temp = ctypes.c_uint()
        watts = ctypes.c_uint()
        try:
            if lib.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(util)) != 0:
                return None
            if lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem)) != 0:
                return None
            lib.nvmlDeviceGetTemperature(handle, 0, ctypes.byref(temp))
            power = (
                watts.value / 1000.0
                if lib.nvmlDeviceGetPowerUsage(handle, ctypes.byref(watts)) == 0
                else 0.0
            )
        except (OSError, AttributeError):
            return None

        return {
            "util": float(util.gpu),
            "vram_used": mem.used / 1024.0 ** 3,
            "vram_total": mem.total / 1024.0 ** 3,
            "temp": float(temp.value),
            "power": power,
        }

    def _sample_smi(self) -> dict | None:
        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    f"--query-gpu={self.QUERY}",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=self.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if out.returncode != 0 or not out.stdout.strip():
            return None

        parts = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
        if len(parts) < 6:
            return None
        try:
            data = {
                "util": float(parts[1]) if parts[1].lower() != "[n/a]" else 0.0,
                "vram_used": float(parts[2]) / 1024.0,
                "vram_total": float(parts[3]) / 1024.0,
                "temp": float(parts[4]),
                "power": float(parts[5]) if parts[5].lower() not in ("[n/a]", "[not supported]") else 0.0,
            }
        except ValueError:
            return None

        with self._lock:
            if self._name is None:
                self._name = self._short_name(parts[0])
        return data

    # ------------------------------------------------------------- public --

    def start(self) -> None:
        threading.Thread(target=self._loop, name="gpu-sampler", daemon=True).start()

    def set_interval(self, seconds: float) -> None:
        self._interval = max(0.5, float(seconds))

    def stop(self) -> None:
        self._stop.set()
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except (OSError, AttributeError):
                pass

    def read(self) -> dict | None:
        with self._lock:
            return dict(self._data) if self._data else None

    @property
    def name(self) -> str | None:
        with self._lock:
            return self._name

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            self._sample()
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.1, self._interval - elapsed))

    def _sample(self) -> None:
        data = self._sample_nvml() if self._nvml is not None else self._sample_smi()
        if data is None:
            self.available = False
            return
        with self._lock:
            self._data = data
        self.available = True


# --------------------------------------------------------------------------- #
#  Global hotkey (own thread + message loop)
# --------------------------------------------------------------------------- #

class HotkeyListener(threading.Thread):
    """Registers global hotkeys on its own thread and pumps their messages."""

    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012

    def __init__(self, bindings: dict[str, tuple[tuple[str, ...], str]], on_press) -> None:
        super().__init__(name="hotkey", daemon=True)
        self.bindings = bindings
        self.on_press = on_press
        self.registered = threading.Event()
        self.ok: dict[str, bool] = {name: False for name in bindings}
        self._ids: dict[int, str] = {}
        self._thread_id = 0
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
        self._user32.GetMessageW.argtypes = [
            ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT
        ]

    def run(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        for index, (name, (mods, key)) in enumerate(self.bindings.items(), start=1):
            flags = sum(MOD_FLAGS[m] for m in mods) | 0x4000  # MOD_NOREPEAT
            if self._user32.RegisterHotKey(None, index, flags, VK_CODES[key.lower()]):
                self._ids[index] = name
                self.ok[name] = True
        self.registered.set()
        if not any(self.ok.values()):
            return

        msg = wt.MSG()
        try:
            while self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY:
                    name = self._ids.get(int(msg.wParam))
                    if name:
                        self.on_press(name)
        finally:
            for index in self._ids:
                self._user32.UnregisterHotKey(None, index)

    def available(self, name: str) -> bool:
        return bool(self.ok.get(name))

    def quit(self) -> None:
        if self._thread_id:
            self._user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)


# --------------------------------------------------------------------------- #
#  Drawing helpers
# --------------------------------------------------------------------------- #

def capsule_points(x1, y1, x2, y2, r):
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    if r <= 0.5:
        return [x1, y1, x2, y1, x2, y2, x1, y2]
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def rounded(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    return canvas.create_polygon(capsule_points(x1, y1, x2, y2, r), smooth=True, **kw)


def speed_parts(value: float) -> tuple[str, str]:
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if value < 1024 or unit == "GB/s":
            break
        value /= 1024.0
    if value >= 100:
        text = f"{value:.0f}"
    elif value >= 10:
        text = f"{value:.1f}"
    else:
        text = f"{value:.2f}"
    return text, unit


def fmt_speed(value: float) -> str:
    number, unit = speed_parts(value)
    return f"{number} {unit}"


class AboutDialog(tk.Toplevel):
    """Frameless about card, centred over the widget."""

    def __init__(self, parent: "Widget") -> None:
        super().__init__(parent)
        self.parent = parent
        # Like the right-click menu, the card keeps the normal size; only the
        # widget itself is resized.
        s = parent.dpi_scale
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=COL_KEY)
        try:
            self.attributes("-transparentcolor", COL_KEY)
        except tk.TclError:
            pass
        self.attributes("-topmost", True)

        W = round(366 * s)
        H = round(306 * s)
        self.canvas = tk.Canvas(
            self, width=W, height=H, bg=COL_KEY, highlightthickness=0, bd=0
        )
        self.canvas.pack()
        rounded(
            self.canvas, 0.5, 0.5, W - 0.5, H - 0.5, 12 * s,
            fill=COL_BG, outline=COL_BORDER, width=max(1, round(s)),
        )

        family = parent.font_family
        f_title = tkfont.Font(family=family, size=-round(12 * s), weight="bold")
        f_name = tkfont.Font(family=family, size=-round(21 * s), weight="bold")
        f_small = tkfont.Font(family=family, size=-round(11 * s))
        f_body = tkfont.Font(family=family, size=-round(12 * s))
        f_email = tkfont.Font(family=family, size=-round(12 * s), underline=True)
        self._fonts = (f_title, f_name, f_small, f_body, f_email)

        pad = round(18 * s)
        y = round(16 * s)

        # three-bar logo
        for offset, width, colour in ((0, 13, "#4c9aff"), (5, 18, "#b07cff"), (10, 9, "#2dd4a7")):
            self.canvas.create_rectangle(
                pad, y + round(offset * s), pad + round(width * s), y + round((offset + 3) * s),
                fill=colour, outline="",
            )
        self.canvas.create_text(
            pad + round(26 * s), y - round(1 * s), text="SYSTEM WIDGET",
            anchor="nw", font=f_title, fill=COL_HEADER,
        )
        self.canvas.create_text(
            W - pad, y - round(1 * s), text=f"v{VERSION}",
            anchor="ne", font=f_title, fill=COL_HEADER,
        )

        def divider(dy):
            self.canvas.create_line(
                pad, round(dy * s), W - pad, round(dy * s),
                fill="#1b2130", width=max(1, round(s)),
            )

        divider(36)

        self.canvas.create_text(
            pad, round(44 * s), text=DEVELOPER, anchor="nw",
            font=f_name, fill=COL_VALUE,
        )
        self.canvas.create_text(
            pad, round(70 * s), text="Developer", anchor="nw",
            font=f_small, fill=COL_DETAIL,
        )

        rows = (
            ("Email", EMAIL, "email"),
            ("Version", VERSION, None),
            ("Created", CREATED, None),
        )
        row_y = 92
        for label, value, tag in rows:
            self.canvas.create_text(
                pad, round(row_y * s), text=label, anchor="nw",
                font=f_small, fill=COL_DETAIL,
            )
            item = self.canvas.create_text(
                pad + round(58 * s), round(row_y * s), text=value, anchor="nw",
                font=f_email if tag == "email" else f_body,
                fill="#6ea8ff" if tag == "email" else COL_LABEL,
                tags=("email",) if tag == "email" else (),
            )
            if tag == "email":
                self.canvas.tag_bind(item, "<Button-1>", self._open_mail)
                self.canvas.tag_bind(item, "<Enter>", lambda _e: self.canvas.configure(cursor="hand2"))
                self.canvas.tag_bind(item, "<Leave>", lambda _e: self.canvas.configure(cursor=""))
            row_y += 18

        divider(150)

        self.canvas.create_text(
            pad, round(158 * s), text="ABOUT ME", anchor="nw",
            font=f_title, fill=COL_HEADER,
        )
        self.canvas.create_text(
            pad, round(176 * s), text=ABOUT_TEXT, anchor="nw",
            font=f_body, fill=COL_LABEL, width=W - 2 * pad, justify="left",
        )

        divider(258)

        self.canvas.create_text(
            pad, round(270 * s), text="Built with Python & Tkinter", anchor="nw",
            font=f_small, fill=COL_DETAIL,
        )

        btn_x1 = W - pad - round(72 * s)
        btn_y1 = round(264 * s)
        btn_x2, btn_y2 = W - pad, round(290 * s)
        close_bg = rounded(
            self.canvas, btn_x1, btn_y1, btn_x2, btn_y2, 7 * s,
            fill="#1b2230", outline=COL_BORDER, tags=("close",),
        )
        close_text = self.canvas.create_text(
            (btn_x1 + btn_x2) / 2, (btn_y1 + btn_y2) / 2, text="Close",
            font=f_body, fill=COL_LABEL, tags=("close",),
        )
        for item in (close_bg, close_text):
            self.canvas.tag_bind(item, "<Button-1>", lambda _e: self.close())
            self.canvas.tag_bind(item, "<Enter>", lambda _e, i=close_bg: self.canvas.itemconfigure(i, fill="#26314a"))
            self.canvas.tag_bind(item, "<Leave>", lambda _e, i=close_bg: self.canvas.itemconfigure(i, fill="#1b2230"))

        # position over the widget, clamped to the work area
        left, top, right, bottom = parent._work_area()
        x = parent.winfo_x() + (parent.winfo_width() - W) // 2
        y = parent.winfo_y() + (parent.winfo_height() - H) // 2
        x = max(left, min(x, right - W))
        y = max(top, min(y, bottom - H))
        self.geometry(f"{W}x{H}+{x}+{y}")

        self.bind("<Escape>", lambda _e: self.close())
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)

        self.deiconify()
        self.grab_set()
        self.focus_force()

    # ------------------------------------------------------------------ ui --

    def _drag_start(self, event) -> None:
        current = self.canvas.find_withtag("current")
        if current:
            tags = self.canvas.gettags(current[0])
            if "email" in tags or "close" in tags:
                return
        self._drag_origin = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _drag_move(self, event) -> None:
        origin = getattr(self, "_drag_origin", None)
        if origin:
            self.geometry(f"+{event.x_root - origin[0]}+{event.y_root - origin[1]}")

    def _open_mail(self, _event) -> None:
        webbrowser.open(f"mailto:{EMAIL}")

    def close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class PopupMenu(tk.Toplevel):
    """Frameless dark popup used for the right-click menu.

    tk.Menu draws its cascade arrows in colours that vanish on a dark
    background, so the menu is drawn on a canvas instead: rounded panel,
    our own check / radio markers and sections that expand in place.
    """

    ROW_H = 27              # row height at 100 % scaling
    SEP_H = 9
    SLIDER_H = 44
    PAD_TOP = 6
    PAD_X = 12
    ICON_W = 22
    CHEV_W = 16
    ACCEL_GAP = 18
    INDENT = 20
    MIN_W = 176

    ACCENT = "#4c9aff"
    CHEVRON = "#7f8b9f"
    HOVER_BG = "#1c2537"
    MARK_OFF = "#3a4457"
    SEP_COLOR = "#1f2634"

    def __init__(self, owner, items, screen_x: int, screen_y: int) -> None:
        super().__init__(owner)
        self.owner = owner
        # The menu is a control surface: it keeps the normal size even when the
        # widget itself is enlarged or shrunk.
        self.s = owner.dpi_scale
        self.items = items
        self.hover: int | None = None
        self.drag_item: dict | None = None
        self.rows: list[tuple[dict, int, int, int]] = []    # item, y1, y2, depth
        self.slider_geom: dict[int, tuple] = {}
        self.W = 0
        self.H = 0

        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=COL_KEY)
        try:
            self.attributes("-transparentcolor", COL_KEY)
        except tk.TclError:
            pass
        self.attributes("-topmost", True)

        family = owner.font_family
        # Sizes in pixels (negative), so "tk scaling" cannot blow the menu up.
        self.f_item = tkfont.Font(family=family, size=-round(12 * self.s))
        self.f_accel = tkfont.Font(family=family, size=-round(11 * self.s))
        self._fonts = (self.f_item, self.f_accel)

        self._measure()
        self.canvas = tk.Canvas(
            self, width=self.W, height=self.H, bg=COL_KEY,
            highlightthickness=0, bd=0,
        )
        self.canvas.pack()
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-3>", self._on_press)
        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<FocusOut>", self._on_focus_out)
        self._render()
        self.show_at(screen_x, screen_y)

    # ----------------------------------------------------------- geometry --

    def _visible_items(self) -> list[tuple[dict, int]]:
        flat: list[tuple[dict, int]] = []
        for item in self.items:
            flat.append((item, 0))
            if item["kind"] == "section" and item.get("expanded"):
                for child in item["items"]:
                    flat.append((child, 1))
        return flat

    def _text(self, item: dict, key: str) -> str:
        value = item.get(key)
        if callable(value):
            value = value()
        return str(value) if value else ""

    def _measure(self) -> None:
        s = self.s
        pad_x = round(self.PAD_X * s)
        indent = round(self.INDENT * s)
        flat = self._visible_items()

        has_mark = any(item["kind"] in ("check", "radio") for item, _d in flat)
        has_section = any(item["kind"] == "section" for item in self.items)
        icon_w = round(self.ICON_W * s) if has_mark else 0
        chev_w = round(self.CHEV_W * s) if has_section else 0

        label_w = 0
        accel_w = 0
        for item, depth in flat:
            label_w = max(
                label_w,
                self.f_item.measure(self._text(item, "label")) + (indent if depth else 0),
            )
            accel_w = max(accel_w, self.f_accel.measure(self._text(item, "accel")))

        gap = round(self.ACCEL_GAP * s)
        self.W = int(max(
            pad_x * 2 + icon_w + label_w + gap + accel_w + chev_w,
            round(self.MIN_W * s),
        ))

        y = round(self.PAD_TOP * s)
        self.rows = []
        self.slider_geom = {}
        for item, depth in flat:
            if item["kind"] == "separator":
                height = round(self.SEP_H * s)
            elif item["kind"] == "slider":
                height = round(self.SLIDER_H * s)
            else:
                height = round(self.ROW_H * s)
            self.rows.append((item, y, y + height, depth))
            if item["kind"] == "slider":
                left = pad_x + (indent if depth else 0)
                self.slider_geom[id(item)] = (
                    left,                                  # track start
                    self.W - pad_x - round(2 * s),         # track end
                    y + round(18 * s),                     # track centre
                    y + round(30 * s),                     # min / max captions
                )
            y += height
        self.H = int(y + round(self.PAD_TOP * s))

        self._pad_x = pad_x
        self._indent = indent
        self._icon_w = icon_w
        self._accel_right = self.W - pad_x - chev_w

    def show_at(self, x: int, y: int) -> None:
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        x = max(2, min(int(x), screen_w - self.W - 2))
        y = max(2, min(int(y), screen_h - self.H - 2))
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self.deiconify()
        self.lift()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_force()

    def _relayout(self) -> None:
        x, y = self.winfo_rootx(), self.winfo_rooty()
        self._measure()
        self.canvas.config(width=self.W, height=self.H)
        screen_h = self.winfo_screenheight()
        if y + self.H > screen_h - 2:
            y = max(2, screen_h - self.H - 2)
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self._render()

    # ------------------------------------------------------------ drawing --

    def _render(self) -> None:
        s = self.s
        c = self.canvas
        for item, _depth in self._visible_items():
            sync = item.get("sync")
            if sync is None:
                continue
            value = bool(sync())
            if item["kind"] == "check":
                item["checked"] = value
            elif item["kind"] == "radio":
                item["selected"] = value

        c.delete("all")
        rounded(
            c, 0.5, 0.5, self.W - 0.5, self.H - 0.5, round(10 * s),
            fill=COL_BG, outline=COL_BORDER, width=max(1, round(s)),
        )
        self._draw_hover()
        for item, y1, y2, depth in self.rows:
            mid = (y1 + y2) / 2
            kind = item["kind"]
            if kind == "separator":
                c.create_line(
                    self._pad_x, mid, self.W - self._pad_x, mid,
                    fill=self.SEP_COLOR, width=max(1, round(s)),
                )
                continue

            left = self._pad_x + (self._indent if depth else 0)
            if kind == "slider":
                self._draw_slider(item, y1, s)
                continue
            if kind in ("check", "radio"):
                self._draw_marker(item, left, mid, s)
            enabled = item.get("enabled", True)
            c.create_text(
                left + self._icon_w, mid,
                text=self._text(item, "label"), anchor="w",
                font=self.f_item, fill=COL_LABEL if enabled else COL_DETAIL,
            )
            accel = self._text(item, "accel")
            if accel:
                c.create_text(
                    self._accel_right, mid, text=accel, anchor="e",
                    font=self.f_accel, fill=COL_DETAIL,
                )
            if kind == "section":
                self._draw_chevron(mid, s, bool(item.get("expanded")))

    def _draw_marker(self, item: dict, x: float, mid: float, s: float) -> None:
        c = self.canvas
        left = x + round(2 * s)
        if item["kind"] == "check":
            size = round(12 * s)
            toggled = bool(item.get("checked"))
            rounded(
                c, left, mid - size / 2, left + size, mid + size / 2, round(3 * s),
                fill=self.ACCENT if toggled else COL_BG,
                outline=self.ACCENT if toggled else self.MARK_OFF,
                width=max(1, round(s)),
            )
            if toggled:
                c.create_line(
                    left + size * 0.26, mid + size * 0.02,
                    left + size * 0.44, mid + size * 0.22,
                    left + size * 0.78, mid - size * 0.24,
                    fill=COL_BG, width=max(1, round(1.8 * s)),
                    capstyle="round", joinstyle="round",
                )
        else:
            r = round(5 * s)
            selected = bool(item.get("selected"))
            c.create_oval(
                left, mid - r, left + 2 * r, mid + r,
                outline=self.ACCENT if selected else self.MARK_OFF,
                width=max(1, round(1.4 * s)),
            )
            if selected:
                dot = round(2.6 * s)
                c.create_oval(
                    left + r - dot, mid - dot, left + r + dot, mid + dot,
                    fill=self.ACCENT, outline="",
                )

    def _value(self, item: dict) -> float:
        value = item.get("sync")
        if callable(value):
            value = value()
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(item.get("min") or 0.0)

    def _slider_frac(self, item: dict, x: float | None = None) -> float:
        x0, x1, _ty, _cy = self.slider_geom[id(item)]
        if x is None:
            value = self._value(item)
            lo, hi = float(item["min"]), float(item["max"])
            frac = 0.0 if hi <= lo else (value - lo) / (hi - lo)
        else:
            frac = (x - x0) / max(1.0, x1 - x0)
        return max(0.0, min(1.0, frac))

    def _slider_value(self, item: dict, x: float) -> float:
        lo, hi = float(item["min"]), float(item["max"])
        step = float(item.get("step") or 0.05)
        value = lo + self._slider_frac(item, x) * (hi - lo)
        value = round(value / step) * step
        return max(lo, min(hi, round(value, 3)))

    def _draw_slider(self, item: dict, y1: float, s: float) -> None:
        c = self.canvas
        x0, x1, ty, cy = self.slider_geom[id(item)]
        frac = self._slider_frac(item)
        knob_x = x0 + frac * (x1 - x0)

        thickness = max(2, round(4 * s))
        rounded(
            c, x0, ty - thickness / 2, x1, ty + thickness / 2,
            thickness / 2.0, fill=COL_TRACK, outline="",
        )
        if knob_x - x0 > 1:
            rounded(
                c, x0, ty - thickness / 2, knob_x, ty + thickness / 2,
                thickness / 2.0, fill=self.ACCENT, outline="",
            )
        radius = round(6 * s)
        c.create_oval(
            knob_x - radius, ty - radius, knob_x + radius, ty + radius,
            fill=self.ACCENT, outline=COL_BG, width=max(1, round(2 * s)),
        )
        lo, hi = float(item["min"]), float(item["max"])
        c.create_text(
            x0, cy, text=f"{round(lo * 100)}%", anchor="nw",
            font=self.f_accel, fill=COL_DETAIL,
        )
        c.create_text(
            x1, cy, text=f"{round(hi * 100)}%", anchor="ne",
            font=self.f_accel, fill=COL_DETAIL,
        )
        c.create_text(
            (x0 + x1) / 2, cy, text=f"{round(self._value(item) * 100)}%",
            anchor="n", font=self.f_accel, fill=COL_VALUE,
        )

    def _draw_chevron(self, mid: float, s: float, expanded: bool) -> None:
        x = self.W - self._pad_x - round(5 * s)
        arm = round(4 * s)
        width = max(1, round(1.6 * s))
        if expanded:
            points = (x - arm, mid - arm * 0.5, x, mid + arm * 0.5, x + arm, mid - arm * 0.5)
        else:
            points = (x - arm * 0.5, mid - arm, x + arm * 0.5, mid, x - arm * 0.5, mid + arm)
        self.canvas.create_line(
            *points, fill=self.CHEVRON, width=width,
            capstyle="round", joinstyle="round",
        )

    def _draw_hover(self) -> None:
        if self.hover is None or self.hover >= len(self.rows):
            return
        item, y1, y2, _depth = self.rows[self.hover]
        if item["kind"] == "separator":
            return
        s = self.s
        rounded(
            self.canvas, round(4 * s), y1 + 1, self.W - round(4 * s), y2 - 1,
            round(6 * s), fill=self.HOVER_BG, outline="",
        )

    # ------------------------------------------------------------- events --

    def _row_at(self, y: int) -> int | None:
        for index, (_item, y1, y2, _depth) in enumerate(self.rows):
            if y1 <= y < y2:
                return index
        return None

    def _inside(self, x: int, y: int) -> bool:
        return 0 <= x <= self.W and 0 <= y <= self.H

    def _on_motion(self, event) -> None:
        if self.drag_item is not None:
            return
        index = self._row_at(event.y)
        if index != self.hover:
            self.hover = index
            self._render()

    def _on_drag(self, event) -> None:
        if self.drag_item is not None:
            self._drag_slider(self.drag_item, event.x)

    def _drag_slider(self, item: dict, x: float) -> None:
        value = self._slider_value(item, x)
        if abs(value - self._value(item)) < 1e-9:
            return
        callback = item.get("on_change")
        if callback is not None:
            callback(value)
        self._render()

    def _on_press(self, event) -> None:
        if not self._inside(event.x, event.y):
            self.close()
            return
        index = self._row_at(event.y)
        if index is None:
            return
        item = self.rows[index][0]
        if item["kind"] == "slider":
            self.drag_item = item
            self.hover = index
            self._drag_slider(item, event.x)

    def _on_focus_out(self, _event) -> None:
        # A grab only catches clicks inside this application, so a click on
        # another window is noticed by the focus leaving the popup.
        self.after(80, self._close_if_unfocused)

    def _close_if_unfocused(self) -> None:
        try:
            if self.focus_get() is None:
                self.close()
        except (tk.TclError, KeyError):
            self.close()

    def _on_release(self, event) -> None:
        if self.drag_item is not None:
            item, self.drag_item = self.drag_item, None
            done = item.get("on_done")
            if done is not None:
                done(self._value(item))
            self.hover = self._row_at(event.y)
            self._render()
            return
        if not self._inside(event.x, event.y):
            return
        index = self._row_at(event.y)
        if index is None:
            return
        item = self.rows[index][0]
        kind = item["kind"]

        if kind == "section":
            self._toggle_section(item)
            return

        if kind == "command":
            if not item.get("enabled", True):
                return
            self.close()
            self.owner.after_idle(item["command"])
            return

        if kind == "check":
            item["checked"] = not bool(item.get("checked"))
            callback = item.get("on_toggle")
            if callback is not None:
                result = callback(item["checked"])
                if isinstance(result, bool):
                    item["checked"] = result
        elif kind == "radio":
            if item.get("selected"):
                return
            group = item.get("group")
            for other in self.items:
                if other.get("group") == group:
                    other["selected"] = other is item
            callback = item.get("on_select")
            if callback is not None:
                callback()

        self._relayout()

    def _toggle_section(self, item: dict) -> None:
        opening = not item.get("expanded")
        for other in self.items:
            if other["kind"] == "section":
                other["expanded"] = False
        item["expanded"] = opening
        self.hover = None
        self._relayout()

    def close(self) -> None:
        try:
            if self.grab_current() == self:
                self.grab_release()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
        if getattr(self.owner, "_menu", None) is self:
            self.owner._menu = None


class Widget(tk.Tk):
    def __init__(self, gpu: GpuSampler, hotkey: HotkeyListener) -> None:
        super().__init__()
        self.settings = load_settings()
        self.gpu = gpu
        self.hotkey = hotkey
        self._about: AboutDialog | None = None
        self._menu: PopupMenu | None = None

        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=COL_KEY)
        try:
            self.attributes("-transparentcolor", COL_KEY)
        except tk.TclError:
            pass
        self.attributes("-topmost", bool(self.settings["topmost"]))
        self.attributes("-alpha", float(self.settings["opacity"]))

        # Display DPI plus the user's own size factor: every dimension in the
        # themes is multiplied by self.scale, and Tk's point-based fonts are
        # scaled by the same factor through "tk scaling".  The DPI is read once
        # and cached: "winfo fpixels 1i" follows "tk scaling", so reading it
        # again would compound the factor on every size change.
        self.dpi_px = self.winfo_fpixels("1i")
        self.dpi_scale = self.dpi_px / 96.0
        self.ui_scale = float(self.settings["ui_scale"])
        self._apply_scale()

        self.W = round(BASE_W * self.scale)
        self.H = 0
        self.visible: list[str] = []
        self.rows: dict[str, dict] = {}
        self.targets: dict[str, float] = {}
        self.shown: dict[str, float] = {}
        self._lock_items: list[int] = []
        self._drag_origin: tuple[int, int] | None = None
        self._auto_hidden = False       # hidden because a game owns the screen
        self._user_hidden = False       # hidden with Ctrl+Alt+W
        self.history: dict[str, deque] = {
            "net": deque(maxlen=40), "power": deque(maxlen=40),
        }

        net = psutil.net_io_counters()
        self._net_prev = net
        self._net_time = time.monotonic()

        self._build_fonts()
        self._build_ui()
        self._bind_events()

        self.deiconify()
        self._apply_window_style()

        box, _ = self._monitor_info()
        self._screen_rect = box
        self._screen_dpi = int(_user32.GetDpiForWindow(self._window_handle()) or 96)

        if not self.settings.get("scale_ref_w") or not self.settings.get("scale_ref_h"):
            self.settings["scale_ref_w"] = box[2] - box[0]
            self.settings["scale_ref_h"] = box[3] - box[1]
            save_settings(self.settings)
        self._apply_display_scale()
        if self.settings.get("corner_dx") is None or self.settings.get("corner_dy") is None:
            self._remember_corner()         # first run with this setting
            save_settings(self.settings)
        else:
            self._place_from_corner()

        psutil.cpu_percent(interval=None)   # prime the counter
        self.after(60, self.refresh)
        self.after(100, self._tick_animation)
        self.after(150, self._check_hotkey)
        self.after(1200, self._enforce_top)

    # ---------------------------------------------------------------- setup --

    def _apply_scale(self) -> None:
        self.scale = self.dpi_scale * self.ui_scale
        self.tk.call("tk", "scaling", self.dpi_px / 72.0 * self.ui_scale)

    def _build_fonts(self) -> None:
        families = set(tkfont.families(self))
        family = next(
            (f for f in ("Segoe UI Variable Display", "Segoe UI", "Tahoma") if f in families),
            "Tahoma",
        )
        self.font_family = family
        self.f_header = tkfont.Font(family=family, size=9, weight="bold")
        self.f_label = tkfont.Font(family=family, size=9)
        self.f_detail = tkfont.Font(family=family, size=8)
        self.f_value = tkfont.Font(family=family, size=15, weight="bold")
        self.f_value_md = tkfont.Font(family=family, size=13, weight="bold")
        self.f_value_sm = tkfont.Font(family=family, size=10, weight="bold")
        self.f_ring = tkfont.Font(family=family, size=11, weight="bold")
        self.f_ring_unit = tkfont.Font(family=family, size=7)
        self.f_ring_detail = tkfont.Font(family=family, size=8)

    def _start_canvas(self, width: int, height: int, radius: float = 12) -> None:
        s = self.scale
        self.W, self.H = width, height
        self.canvas = tk.Canvas(
            self, width=width, height=height, bg=COL_KEY,
            highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        rounded(
            self.canvas, 0.5, 0.5, width - 0.5, height - 0.5, radius * s,
            fill=COL_BG, outline=COL_BORDER, width=max(1, round(s)),
        )
        self.rows = {}
        self.targets = {}
        self.shown = {}
        self._lock_items = []
        self.gpu_label = None

    def _build_ui(self) -> None:
        previous = None
        if getattr(self, "canvas", None) is not None and self.winfo_ismapped():
            previous = (self.winfo_x(), self.winfo_y(), self.W, self.H)

        if getattr(self, "canvas", None) is not None:
            self.canvas.destroy()

        self.visible = [key for key in ALL_ROW_KEYS if key in self.settings["rows"]]
        theme = self.settings["theme"]
        if theme == "strip":
            self._build_strip()
        elif theme == "minimal":
            self._build_minimal()
        elif theme == "rings":
            self._build_rings()
        else:
            self._build_card()
        self._resize_window()
        if previous is not None:
            self._keep_corner(*previous)
        self._update_lock_icon()

    def _update_lock_icon(self) -> None:
        """Small padlock in the top-right corner while the widget is locked."""
        for item in self._lock_items:
            try:
                self.canvas.delete(item)
            except tk.TclError:
                pass
        self._lock_items = []
        if not self.settings.get("locked"):
            return

        s = self.scale
        right = self.W - round(5 * s)
        left = right - round(7 * s)
        top = round(4 * s)
        colour = COL_DETAIL
        self._lock_items.append(self.canvas.create_oval(
            left + 1.5 * s, top, right - 1.5 * s, top + 5 * s,
            outline=colour, width=max(1, round(1.2 * s)),
        ))
        self._lock_items.append(self.canvas.create_rectangle(
            left, top + 3.5 * s, right, top + 8 * s,
            fill=colour, outline="",
        ))

    def _keep_corner(self, x0: int, y0: int, w0: int, h0: int) -> None:
        """After a resize, stay hugging the screen corner the widget was in."""
        left, top, right, bottom = self._bounds()
        # Only a widget docked near an edge keeps that edge fixed; one sitting
        # in the middle of the screen just grows to the right and downward.
        if right - (x0 + w0) <= (right - left) * 0.15:
            x = x0 + w0 - self.W
        else:
            x = x0
        if bottom - (y0 + h0) <= (bottom - top) * 0.15:
            y = y0 + h0 - self.H
        else:
            y = y0
        x = max(left, min(int(x), right - self.W))
        y = max(top, min(int(y), bottom - self.H))
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")
        if (x, y) != (self.settings["x"], self.settings["y"]):
            self.settings["x"], self.settings["y"] = x, y
            save_settings(self.settings)

    # ---------------------------------------------------------- theme: card --

    def _build_card(self) -> None:
        s = self.scale
        width = round(BASE_W * s)
        height = round(
            (HEADER_H + (len(self.visible) - 1) * ROW_H + BAR_OFFSET + BAR_H + BOTTOM_PAD) * s
        )
        self._start_canvas(width, height)

        pad = round(16 * s)
        self.canvas.create_text(
            pad, round(15 * s), text="PERFORMANCE", anchor="nw",
            font=self.f_header, fill=COL_HEADER,
        )
        self.gpu_label = self.canvas.create_text(
            width - pad, round(15 * s), text="", anchor="ne",
            font=self.f_header, fill=COL_HEADER,
        )
        self.canvas.create_line(
            pad, round(35 * s), width - pad, round(35 * s),
            fill="#1b2130", width=max(1, round(s)),
        )

        top = HEADER_H * s
        block = ROW_H * s
        for index, key in enumerate(self.visible):
            spec = ROW_BY_KEY[key]
            y = top + index * block
            dot_y = y + 6 * s
            self.canvas.create_oval(
                pad, dot_y - 3 * s, pad + 6 * s, dot_y + 3 * s,
                fill=spec.accent, outline="",
            )
            self.canvas.create_text(
                pad + 13 * s, y + 1 * s, text=spec.label, anchor="nw",
                font=self.f_label, fill=COL_LABEL,
            )
            detail = self.canvas.create_text(
                pad + 13 * s + self.f_label.measure(spec.label) + 10 * s, y + 3 * s,
                text="", anchor="nw", font=self.f_detail, fill=COL_DETAIL,
            )
            value = self.canvas.create_text(
                width - pad, y - 4 * s, text="", anchor="ne",
                font=self.f_value, fill=COL_VALUE,
            )

            bar_y = y + BAR_OFFSET * s
            bar_h = BAR_H * s
            self.canvas.create_rectangle(
                pad, bar_y, width - pad, bar_y + bar_h,
                fill=COL_TRACK, outline="",
            )
            fill = rounded(
                self.canvas, pad, bar_y, pad, bar_y + bar_h,
                bar_h / 2.0, fill=spec.accent, outline="",
            )

            self.rows[key] = {
                "kind": "card",
                "x1": pad,
                "x2": width - pad,
                "y": bar_y,
                "h": bar_h,
                "fill": fill,
                "value": value,
                "detail": detail,
                "last_width": None,
                "ring": None,
            }

    # --------------------------------------------------------- theme: strip --

    def _build_strip(self) -> None:
        s = self.scale
        widths = {"percent": 104, "speed": 156, "watts": 132, "temp": 96}
        gap = 10
        pad = 14
        parts = [widths[ROW_BY_KEY[key].kind] for key in self.visible]
        width = round((2 * pad + sum(parts) + gap * (len(parts) - 1)) * s)
        height = round(52 * s)
        self._start_canvas(width, height, radius=10)

        x = pad * s
        for key in self.visible:
            spec = ROW_BY_KEY[key]
            w = widths[spec.kind] * s
            self.canvas.create_oval(
                x + 2 * s, 15 * s, x + 8 * s, 21 * s,
                fill=spec.accent, outline="",
            )
            self.canvas.create_text(
                x + 12 * s, 12 * s, text=spec.label, anchor="nw",
                font=self.f_label, fill=COL_LABEL,
            )
            value = self.canvas.create_text(
                x + w, 9 * s, text="", anchor="ne",
                font=self.f_value_md, fill=COL_VALUE,
            )

            bar_y = 35 * s
            bar_h = 4 * s
            self.canvas.create_rectangle(
                x, bar_y, x + w, bar_y + bar_h, fill=COL_TRACK, outline="",
            )
            fill = rounded(
                self.canvas, x, bar_y, x, bar_y + bar_h,
                bar_h / 2.0, fill=spec.accent, outline="",
            )
            self.rows[key] = {
                "kind": "strip",
                "x1": x,
                "x2": x + w,
                "y": bar_y,
                "h": bar_h,
                "fill": fill,
                "value": value,
                "detail": None,
                "last_width": None,
                "ring": None,
            }
            x += w + gap * s

    # ------------------------------------------------------- theme: minimal --

    def _build_minimal(self) -> None:
        s = self.scale
        pad = 15
        row_h = 24
        width = round(196 * s)
        height = round((12 + len(self.visible) * row_h + 8) * s)
        self._start_canvas(width, height, radius=10)

        for index, key in enumerate(self.visible):
            spec = ROW_BY_KEY[key]
            mid = (12 + index * row_h + row_h / 2) * s
            self.canvas.create_oval(
                pad * s + 3 * s, mid - 3 * s, pad * s + 9 * s, mid + 3 * s,
                fill=spec.accent, outline="",
            )
            self.canvas.create_text(
                (pad + 13) * s, mid, text=spec.label, anchor="w",
                font=self.f_label, fill=COL_LABEL,
            )
            value = self.canvas.create_text(
                width - pad * s, mid, text="", anchor="e",
                font=self.f_value_sm, fill=COL_VALUE,
            )
            self.rows[key] = {
                "kind": "minimal",
                "x1": 0, "x2": 0, "y": 0, "h": 0, "fill": None,
                "value": value,
                "detail": None,
                "last_width": None,
                "ring": None,
            }

    # --------------------------------------------------------- theme: rings --

    def _build_rings(self) -> None:
        s = self.scale
        diameter = 74
        gap = 16
        pad = 16
        width = round((2 * pad + len(self.visible) * diameter + (len(self.visible) - 1) * gap) * s)
        height = round((pad + diameter + 8 + 14 + 13 + pad) * s)
        self._start_canvas(width, height, radius=12)

        for index, key in enumerate(self.visible):
            spec = ROW_BY_KEY[key]
            cx = (pad + index * (diameter + gap) + diameter / 2) * s
            top = pad * s
            dia = diameter * s
            box = (cx - dia / 2, top, cx + dia / 2, top + dia)

            self.canvas.create_oval(
                box, outline=COL_TRACK, width=round(6 * s),
            )
            ring = self.canvas.create_arc(
                box, start=90, extent=-0.001, style="arc",
                outline=spec.accent, width=round(6 * s),
            )
            cy = top + dia / 2
            value = self.canvas.create_text(
                cx, cy, text="", anchor="center",
                font=self.f_ring, fill=COL_VALUE,
            )
            unit = self.canvas.create_text(
                cx, cy + 9 * s, text="", anchor="center",
                font=self.f_ring_unit, fill=COL_DETAIL,
            )
            self.canvas.create_text(
                cx, top + dia + 6 * s, text=spec.label, anchor="n",
                font=self.f_label, fill=COL_LABEL,
            )
            detail = self.canvas.create_text(
                cx, top + dia + 21 * s, text="", anchor="n",
                font=self.f_ring_detail, fill=COL_DETAIL,
            )

            self.rows[key] = {
                "kind": "ring",
                "cx": cx,
                "cy": cy,
                "ring": ring,
                "fill": None,
                "x1": 0, "x2": 0, "y": 0, "h": 0,
                "value": value,
                "unit": unit,
                "detail": detail,
                "last_width": None,
            }

    # -------------------------------------------------------------- window --

    def _resize_window(self) -> None:
        s = self.scale
        left, top, right, bottom = self._bounds()

        if self.winfo_ismapped():
            x, y = self.winfo_x(), self.winfo_y()
        else:
            x = self.settings["x"]
            y = self.settings["y"]
            if x is None or y is None:
                x = right - self.W - round(24 * s)
                y = bottom - self.H - round(24 * s)

        x = max(left, min(int(x), right - self.W))
        y = max(top, min(int(y), bottom - self.H))
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _monitor_info(self) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
        """Monitor rectangle and work area holding the widget.

        Both are looked up for the widget's own screen, so a second monitor -
        or a game that switches the display to a lower resolution - is placed
        correctly instead of being pushed onto the primary screen.
        """
        monitor = _user32.MonitorFromWindow(
            self._window_handle(), MONITOR_DEFAULTTONEAREST
        )
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if monitor and _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            m, w = info.rcMonitor, info.rcWork
            return (
                (m.left, m.top, m.right, m.bottom),
                (w.left, w.top, w.right, w.bottom),
            )
        screen = (0, 0, self.winfo_screenwidth(), self.winfo_screenheight())
        return screen, screen

    def _bounds(self) -> tuple[int, int, int, int]:
        """Placement limits - the whole monitor when the widget may cover the taskbar."""
        monitor, work = self._monitor_info()
        return monitor if self.settings.get("above_taskbar", True) else work

    def _current_xy(self) -> tuple[int, int]:
        """Where the widget is, also while it is withdrawn."""
        if self.winfo_ismapped():
            return self.winfo_x(), self.winfo_y()
        x, y = self.settings.get("x"), self.settings.get("y")
        if x is None or y is None:
            return self.winfo_x(), self.winfo_y()
        return int(x), int(y)

    def _move_to(self, x: int, y: int) -> None:
        """Move the widget, keeping it inside this monitor."""
        left, top, right, bottom = self._bounds()
        x = max(left, min(int(x), right - self.W))
        y = max(top, min(int(y), bottom - self.H))
        if (x, y) == self._current_xy():
            return
        self.geometry(f"+{x}+{y}")
        self.settings["x"], self.settings["y"] = x, y
        save_settings(self.settings)

    def _remember_corner(self) -> None:
        """Record the gap between the widget and the bottom-right corner.

        Keeping the gap rather than an absolute position is what lets the
        widget land in the same spot on every display mode a game may use,
        and come back to it when the desktop resolution returns.
        """
        left, top, right, bottom = self._bounds()
        x, y = self._current_xy()
        self.settings["corner_dx"] = max(0, right - (x + self.W))
        self.settings["corner_dy"] = max(0, bottom - (y + self.H))

    def _place_from_corner(self) -> None:
        """Put the widget back at its corner gap for the current display."""
        left, top, right, bottom = self._bounds()
        dx = self.settings.get("corner_dx")
        dy = self.settings.get("corner_dy")
        if dx is None or dy is None:
            dx = round(24 * self.scale)
            dy = round(24 * self.scale)
        self._move_to(right - self.W - int(dx), bottom - self.H - int(dy))

    def _auto_scale(self) -> float:
        """Size for the display that is active right now.

        The size you pick belongs to the display you pick it on.  On a smaller
        display - a game running at 1280x720 while the desktop is 1920x1080 -
        the widget shrinks by that same ratio, so it covers the same share of
        the screen instead of looking half again as big.  It never grows past
        your size on larger displays.
        """
        wanted = float(self.settings["ui_scale"])
        if not self.settings.get("adapt_scale", True):
            return wanted
        ref_w = int(self.settings.get("scale_ref_w") or 0)
        ref_h = int(self.settings.get("scale_ref_h") or 0)
        if ref_w <= 0 or ref_h <= 0:
            return wanted
        left, top, right, bottom = self._bounds()
        factor = min(1.0, (right - left) / ref_w, (bottom - top) / ref_h)
        target = max(AUTO_SCALE_FLOOR, min(wanted, wanted * factor))
        return max(AUTO_SCALE_FLOOR, round(target / 0.05) * 0.05)

    def _apply_display_scale(self) -> None:
        """Bring the widget to the size this display should show right now.

        Only the in-memory scale changes: your chosen size is still saved as
        it was and comes back the moment the display is big enough again, for
        example when a game exits.
        """
        left, top, right, bottom = self._bounds()
        avail_w = max(1, right - left)
        avail_h = max(1, bottom - top)
        current = self.ui_scale
        if current <= 0:
            return

        target = self._auto_scale()
        want_w = self.W * target / current
        want_h = self.H * target / current
        if want_w > avail_w or want_h > avail_h:
            # Even the adapted size is too big for this display: keep shrinking
            # until it fits, so it is never half off the screen.
            factor = min(avail_w / want_w, avail_h / want_h) * 0.96
            target = max(AUTO_SCALE_FLOOR, target * factor)
            target = round(target / 0.05) * 0.05

        if abs(target - current) < 1e-6:
            return
        self.ui_scale = target
        self._apply_scale()
        self._build_fonts()
        self._build_ui()

    def _sync_display(self) -> None:
        """Notice resolution or DPI changes, such as a game switching modes.

        Every game can use its own resolution; the widget keeps its size and
        its gap from the bottom-right corner, so it sits in the same place on
        all of them and returns there when the desktop resolution comes back.
        """
        box, _ = self._monitor_info()
        dpi = int(_user32.GetDpiForWindow(self._window_handle()) or 96)
        if box == self._screen_rect and dpi == self._screen_dpi:
            return

        dpi_changed = dpi != self._screen_dpi
        resized = box != self._screen_rect
        self._screen_rect = box
        self._screen_dpi = dpi

        if dpi_changed:
            self.dpi_px = float(dpi)
            self.dpi_scale = self.dpi_px / 96.0
            self._apply_scale()
            self._build_fonts()
            self._build_ui()            # rebuilds at the new size
        if resized:
            self._apply_display_scale()  # proportional for smaller displays
        if dpi_changed or resized:
            self._place_from_corner()

    def _fullscreen_here(self) -> bool:
        """True when a fullscreen app owns the monitor the widget is on.

        A game running fullscreen on *another* monitor does not get in the
        way, so the widget keeps its place there instead of hiding.
        """
        if not fullscreen_app_running():
            return False
        fg = _user32.GetForegroundWindow()
        if not fg:
            return True
        mine = _user32.MonitorFromWindow(self._window_handle(), MONITOR_DEFAULTTONEAREST)
        theirs = _user32.MonitorFromWindow(fg, MONITOR_DEFAULTTONEAREST)
        if not mine or not theirs:
            return True
        return mine == theirs

    def _handle_fullscreen(self) -> bool:
        """Step aside while an exclusive fullscreen app owns the screen.

        Nothing can be drawn over exclusive fullscreen, and re-raising the
        widget while a game holds the display makes some games drop out of
        fullscreen and minimize.  So it hides for the duration and comes back
        by itself when the game is done.  Borderless / windowed games are not
        affected - the widget stays on top of those as usual.
        """
        if not self.settings.get("hide_in_games", True):
            return False
        active = self._fullscreen_here()
        if active:
            if self.state() != "withdrawn":
                self._auto_hidden = True
                self.withdraw()
        elif self._auto_hidden:
            self._auto_hidden = False
            if not self._user_hidden:
                self.show()
        return active

    def _window_handle(self) -> int:
        hwnd = _user32.GetParent(self.winfo_id())
        return hwnd or self.winfo_id()

    def _shell_menu_open(self) -> bool:
        """True while the Start menu or a taskbar flyout is in front.

        Those are shell XAML windows that belong above the widget, so the
        z-order fix is skipped until they close.
        """
        foreground = _user32.GetForegroundWindow()
        if not foreground:
            return False
        buffer = ctypes.create_unicode_buffer(80)
        _user32.GetClassNameW(foreground, buffer, 80)
        return buffer.value == "Windows.UI.Core.CoreWindow" or "Xaml" in buffer.value

    def _taskbar_above(self) -> bool:
        """True when Explorer's taskbar sits above the widget in the z-order."""
        taskbar = _user32.FindWindowW("Shell_TrayWnd", None)
        if not taskbar:
            return False
        hwnd = self._window_handle()
        current = _user32.GetTopWindow(None)
        for _ in range(400):
            if not current:
                break
            if current == hwnd:
                return False
            if current == taskbar:
                return True
            current = _user32.GetWindow(current, 2)  # GW_HWNDNEXT
        return False

    def _blocks_widget(self, window: int, rect) -> bool:
        """True when `window` is drawn over the widget's rectangle."""
        if not _user32.IsWindowVisible(window) or _user32.IsIconic(window):
            return False
        pid = wt.DWORD()
        _user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value == os.getpid():          # our own menu / About card
            return False
        buffer = ctypes.create_unicode_buffer(80)
        _user32.GetClassNameW(window, buffer, 80)
        name = buffer.value
        if name in SHELL_ABOVE or "Xaml" in name or name == "Windows.UI.Core.CoreWindow":
            return False                      # menus, Start, flyouts, toasts
        if _is_cloaked(window):
            return False
        other = wt.RECT()
        if not _user32.GetWindowRect(window, ctypes.byref(other)):
            return False
        return (
            other.left < rect.right
            and other.right > rect.left
            and other.top < rect.bottom
            and other.bottom > rect.top
        )

    def _covered_by_other(self) -> bool:
        """True when another app's window is above the widget and overlaps it.

        Only topmost windows can outrank a topmost widget, so a borderless
        fullscreen game that grabs topmost (or an "always on top" player)
        hides the widget until it is raised again.
        """
        hwnd = self._window_handle()
        rect = wt.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        current = _user32.GetTopWindow(None)
        for _ in range(400):
            if not current:
                return False
            if current == hwnd:
                return False                  # widget reached: nothing on top
            if self._blocks_widget(current, rect):
                return True
            current = _user32.GetWindow(current, GW_HWNDNEXT)
        return False

    def _enforce_top(self) -> None:
        """Keep the widget in front of the taskbar and other topmost windows."""
        delay = 1000
        try:
            self._sync_display()
            if self._handle_fullscreen():
                delay = 1000
            elif self._fullscreen_here():
                # A game owns this display.  Never fight it for the z-order:
                # that is what made exclusive games drop out and minimize.
                # The widget is already topmost, so a borderless or
                # fullscreen-optimised game still shows it.
                delay = 1000
            elif self.settings.get("topmost") and self.state() != "withdrawn":
                above_taskbar = bool(self.settings.get("above_taskbar", True))
                _, work = self._monitor_info()
                work_bottom = work[3]
                overlapping = self.winfo_y() + self.winfo_height() > work_bottom + 1
                if overlapping and above_taskbar:
                    delay = 600
                raise_it = False
                if not self._shell_menu_open():
                    if (
                        overlapping
                        and above_taskbar
                        and self._taskbar_above()
                    ):
                        raise_it = True
                    elif self._covered_by_other():
                        raise_it = True
                if raise_it:
                    self._raise_topmost()
        except tk.TclError:
            pass
        self._top_job = self.after(delay, self._enforce_top)

    def _raise_topmost(self) -> None:
        """Lift the widget to the front of the topmost band.

        HWND_TOPMOST does not reorder an already-topmost window, and the
        NOTOPMOST/TOPMOST dance used for the taskbar lands at the *bottom* of
        the band - enough to beat the taskbar, useless against another
        always-on-top window such as a borderless game.  HWND_TOP moves it to
        the very front without dropping topmost or stealing focus.
        """
        try:
            if not (self.settings.get("topmost") and self.state() != "withdrawn"):
                return
            hwnd = self._window_handle()
            flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOREDRAW
            if not (_user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST):
                _user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
            _user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, flags)
        except tk.TclError:
            pass

    def _place_window(self) -> None:
        """Reset to the bottom-right corner of this screen, above the taskbar."""
        _, work = self._monitor_info()
        left, top, right, bottom = work
        x = right - self.W - round(24 * self.scale)
        y = bottom - self.H - round(24 * self.scale)
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _apply_window_style(self) -> None:
        """Keep it out of Alt-Tab / taskbar."""
        self.update_idletasks()
        hwnd = self._window_handle()
        WS_EX_TOOLWINDOW = 0x00000080
        style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)

    def _bind_events(self) -> None:
        # Bind on the toplevel: events from the canvas (which is recreated
        # whenever the row selection or theme changes) propagate up to it.
        self.bind("<ButtonPress-1>", self._drag_start)
        self.bind("<B1-Motion>", self._drag_move)
        self.bind("<ButtonRelease-1>", self._drag_end)
        self.bind("<Button-3>", self._show_menu)
        self.bind("<Control-MouseWheel>", self._wheel_scale)
        self.bind("<Escape>", lambda _e: self.hide())
        self.protocol("WM_DELETE_WINDOW", self.quit)

    def _drag_start(self, event) -> None:
        if self.settings.get("locked"):
            return
        self._drag_origin = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _drag_move(self, event) -> None:
        if self._drag_origin is None or self.settings.get("locked"):
            return
        ox, oy = self._drag_origin
        self.geometry(f"+{event.x_root - ox}+{event.y_root - oy}")

    def _drag_end(self, _event) -> None:
        self._drag_origin = None
        if self.settings.get("locked"):
            return
        self.settings["x"] = self.winfo_x()
        self.settings["y"] = self.winfo_y()
        self._remember_corner()
        save_settings(self.settings)

    def hide(self) -> None:
        if self._auto_hidden:
            return                        # a game owns the screen
        if not self.hotkey.available("toggle"):
            return
        self._user_hidden = True
        self._close_menu()
        self._close_about()
        self.withdraw()

    def show(self) -> None:
        self._user_hidden = False
        self.deiconify()
        self.attributes("-topmost", bool(self.settings["topmost"]))
        self.lift()
        self.update_idletasks()
        _user32.ShowWindow(self._window_handle(), 4)  # SW_SHOWNOACTIVATE

    def toggle(self) -> None:
        if self._auto_hidden:
            return                        # it comes back when the game ends
        if self.state() == "withdrawn":
            self.show()
        else:
            self.hide()

    def quit(self) -> None:
        self.settings["x"] = self.winfo_x()
        self.settings["y"] = self.winfo_y()
        save_settings(self.settings)
        self._close_menu()
        self._close_about()
        self.gpu.stop()
        self.hotkey.quit()
        try:
            self.destroy()
        except tk.TclError:
            pass

    # --------------------------------------------------------------- about --

    def show_about(self) -> None:
        if self._about is not None and self._about.winfo_exists():
            self._about.lift()
            return
        self._about = AboutDialog(self)

    def _close_about(self) -> None:
        if self._about is not None and self._about.winfo_exists():
            self._about.close()
        self._about = None

    # --------------------------------------------------------------- menu ----

    def _show_menu(self, event) -> None:
        self._close_menu()

        hotkey_text = (
            "+".join(m.capitalize() for m in HOTKEY_MODIFIERS) + "+" + HOTKEY_KEY.upper()
        )
        topmost_text = (
            "+".join(m.capitalize() for m in HOTKEY_MODIFIERS) + "+" + TOPMOST_KEY.upper()
        )
        lock_text = (
            "+".join(m.capitalize() for m in HOTKEY_MODIFIERS) + "+" + LOCK_KEY.upper()
        )

        def check(label, sync, on_toggle, accel=None, enabled=True):
            return {
                "kind": "check", "label": label, "sync": sync,
                "on_toggle": on_toggle, "accel": accel, "enabled": enabled,
            }

        def radio(label, group, sync, on_select):
            return {
                "kind": "radio", "label": label, "group": group,
                "sync": sync, "on_select": on_select,
            }

        show_items = [
            check(
                spec.menu_label or spec.label,
                (lambda k=spec.key: k in self.visible),
                (lambda value, k=spec.key: self._set_row(k, value)),
            )
            for spec in ROWS
        ]

        theme_items = [
            radio(
                THEME_LABELS[key], "theme",
                (lambda k=key: self.settings["theme"] == k),
                (lambda k=key: self._set_theme(k)),
            )
            for key in THEMES
        ]

        size_items = [
            {
                "kind": "slider",
                "min": UI_SCALE_MIN, "max": UI_SCALE_MAX, "step": 0.05,
                "sync": lambda: float(self.settings["ui_scale"]),
                "on_change": lambda value: self._set_scale(value, save=False),
                "on_done": lambda _value: save_settings(self.settings),
            }
        ]

        opacity_items = [
            {
                "kind": "slider",
                "min": OPACITY_MIN, "max": 1.0, "step": 0.05,
                "sync": lambda: float(self.settings["opacity"]),
                "on_change": lambda value: self._set_opacity(value, save=False),
                "on_done": lambda _value: save_settings(self.settings),
            }
        ]

        rate_items = [
            radio(
                f"{sec:g} s", "rate",
                (lambda v=sec: abs(float(self.settings["refresh"]) - v) < 1e-6),
                (lambda v=sec: self._set_refresh(v)),
            )
            for sec in (0.5, 1.0, 1.5, 2.0, 3.0)
        ]

        sections = [
            {
                "kind": "section", "label": "Show", "items": show_items,
                "expanded": False,
                "accel": lambda: (
                    "All rows" if len(self.visible) == len(ROWS)
                    else f"{len(self.visible)} of {len(ROWS)}"
                ),
            },
            {
                "kind": "section", "label": "Theme", "items": theme_items,
                "expanded": False,
                "accel": lambda: THEME_LABELS.get(self.settings["theme"], ""),
            },
            {
                "kind": "section", "label": "Size", "items": size_items,
                "expanded": False,
                "accel": lambda: f"{round(float(self.settings['ui_scale']) * 100)}%",
            },
            {
                "kind": "section", "label": "Opacity", "items": opacity_items,
                "expanded": False,
                "accel": lambda: f"{round(float(self.settings['opacity']) * 100)}%",
            },
            {
                "kind": "section", "label": "Refresh rate", "items": rate_items,
                "expanded": False,
                "accel": lambda: f"{float(self.settings['refresh']):g} s",
            },
        ]

        items = [
            check(
                "Lock widget", lambda: bool(self.settings.get("locked")),
                self._set_locked, accel=lock_text,
            ),
            {"kind": "separator"},
        ] + sections + [
            {"kind": "separator"},
            check(
                "Always on top", lambda: bool(self.settings["topmost"]),
                self._set_topmost, accel=topmost_text,
            ),
            check(
                "Stay above the taskbar",
                lambda: bool(self.settings.get("above_taskbar", True)),
                self._set_above_taskbar,
            ),
            check(
                "Hide in fullscreen games",
                lambda: bool(self.settings.get("hide_in_games", True)),
                self._set_hide_in_games,
            ),
            check(
                "Scale with resolution",
                lambda: bool(self.settings.get("adapt_scale", True)),
                self._set_adapt_scale,
            ),
            check("Start with Windows", autostart_enabled, self._set_autostart),
            {"kind": "separator"},
            {
                "kind": "command", "label": "Hide", "accel": hotkey_text,
                "command": self.hide,
                "enabled": self.hotkey.available("toggle"),
            },
            {"kind": "command", "label": "Reset position", "command": self._reset_position},
            {"kind": "separator"},
            {"kind": "command", "label": "About System Widget", "command": self.show_about},
            {"kind": "command", "label": "Exit", "command": self.quit},
        ]

        self._menu = PopupMenu(self, items, event.x_root, event.y_root)

    def _close_menu(self) -> None:
        menu = self._menu
        self._menu = None
        if menu is not None:
            try:
                menu.close()
            except tk.TclError:
                pass

    def _set_row(self, key: str, value: bool) -> None:
        visible = [k for k in self.visible if k != key]
        if value:
            visible.append(key)
        visible = [k for k in ALL_ROW_KEYS if k in visible]
        if not visible or visible == self.visible:
            return                      # keep at least one row on screen
        self.settings["rows"] = visible
        save_settings(self.settings)
        self._build_ui()

    def _set_theme(self, theme: str) -> None:
        if theme == self.settings["theme"]:
            return
        self.settings["theme"] = theme
        save_settings(self.settings)
        self._build_ui()

    def _set_scale(self, value: float, save: bool = True) -> None:
        value = max(UI_SCALE_MIN, min(UI_SCALE_MAX, round(float(value), 3)))
        # The size belongs to the display it was picked on: from here on it is
        # the reference the proportional scaling is measured against.
        box, _ = self._monitor_info()
        self.settings["scale_ref_w"] = box[2] - box[0]
        self.settings["scale_ref_h"] = box[3] - box[1]
        self.settings["ui_scale"] = value
        if save:
            save_settings(self.settings)
        if abs(value - self.ui_scale) < 1e-6:
            return
        self.ui_scale = value
        self._apply_scale()
        self._build_fonts()
        self._build_ui()

    def _wheel_scale(self, event) -> None:
        if self.settings.get("locked"):
            return
        step = 0.05 if event.delta > 0 else -0.05
        self._set_scale(self.ui_scale + step)

    def _set_topmost(self, value: bool) -> None:
        self.settings["topmost"] = value
        self.attributes("-topmost", value)
        save_settings(self.settings)

    def _toggle_topmost(self) -> None:
        self._set_topmost(not bool(self.settings["topmost"]))

    def _set_opacity(self, value: float, save: bool = True) -> None:
        value = max(OPACITY_MIN, min(1.0, round(float(value), 3)))
        self.settings["opacity"] = value
        self.attributes("-alpha", value)
        if save:
            save_settings(self.settings)

    def _set_above_taskbar(self, value: bool) -> bool:
        self.settings["above_taskbar"] = value
        if value and not self.settings.get("topmost"):
            self._set_topmost(True)
        save_settings(self.settings)
        self._resize_window()
        return value

    def _set_locked(self, value: bool) -> bool:
        value = bool(value)
        self.settings["locked"] = value
        self._drag_origin = None          # drop any half-finished drag
        save_settings(self.settings)
        self._update_lock_icon()
        return value

    def _set_hide_in_games(self, value: bool) -> bool:
        value = bool(value)
        self.settings["hide_in_games"] = value
        save_settings(self.settings)
        if not value and self._auto_hidden:
            self._auto_hidden = False
            if not self._user_hidden:
                self.show()
        return value

    def _set_adapt_scale(self, value: bool) -> bool:
        value = bool(value)
        self.settings["adapt_scale"] = value
        save_settings(self.settings)
        self._apply_display_scale()
        return value

    def _toggle_lock(self) -> None:
        self._set_locked(not bool(self.settings.get("locked")))

    def _set_refresh(self, seconds: float) -> None:
        self.settings["refresh"] = seconds
        self.gpu.set_interval(seconds)
        save_settings(self.settings)

    def _reset_position(self) -> None:
        self._place_window()
        self.update_idletasks()
        self.settings["x"] = self.winfo_x()
        self.settings["y"] = self.winfo_y()
        self._remember_corner()
        save_settings(self.settings)

    def _set_autostart(self, value: bool) -> bool:
        set_autostart(value)
        return autostart_enabled()

    # -------------------------------------------------------------- update ---

    def _check_hotkey(self) -> None:
        if not self.hotkey.registered.is_set():
            return
        missing = [
            name for name in ("toggle", "topmost", "lock")
            if not self.hotkey.available(name)
        ]
        if not missing:
            return

        names = {
            "toggle": f"Ctrl+Alt+{HOTKEY_KEY.upper()} (hide / show)",
            "topmost": f"Ctrl+Alt+{TOPMOST_KEY.upper()} (always on top)",
            "lock": f"Ctrl+Alt+{LOCK_KEY.upper()} (lock / unlock)",
        }
        listed = "\n".join("  • " + names[m] for m in missing)
        ctypes.windll.user32.MessageBoxW(
            None,
            "These hotkeys are already used by another program:\n\n"
            f"{listed}\n\n"
            "The menu still works, but the Hide option stays disabled until you "
            "pick a different key at the top of SystemWidget.pyw.",
            "System Widget",
            0x30,
        )

    def refresh(self) -> None:
        now = time.monotonic()
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()

        if "cpu" in self.rows:
            freq = None
            try:
                f = psutil.cpu_freq()
                freq = f.current / 1000.0 if f and f.current else None
            except Exception:
                pass
            detail = (
                f"{freq:.1f} GHz" if freq
                else f"{psutil.cpu_count(logical=True)} threads"
            )
            self._update_row(
                "cpu", f"{cpu:.0f}%", detail, cpu,
                ring=(f"{cpu:.0f}", "%"),
            )

        if "ram" in self.rows:
            used = mem.used / 1024 ** 3
            total = mem.total / 1024 ** 3
            self._update_row(
                "ram", f"{mem.percent:.0f}%",
                f"{used:.1f} / {total:.0f} GB", mem.percent,
                ring=(f"{mem.percent:.0f}", "%"),
            )

        gpu = self.gpu.read()

        if "gpu" in self.rows:
            if gpu:
                self._update_row(
                    "gpu", f"{gpu['util']:.0f}%",
                    f"{gpu['vram_used']:.1f}/{gpu['vram_total']:.0f} GB VRAM",
                    gpu["util"],
                    ring=(f"{gpu['util']:.0f}", "%"),
                )
            else:
                self._update_row(
                    "gpu", "—", "not detected" if not self.gpu.available else "…",
                    0.0, ring=("—", ""),
                )

        if "temp" in self.rows:
            if gpu:
                temp = gpu["temp"]
                self._update_row(
                    "temp", f"{temp:.0f}°C", "GPU",
                    max(0.0, min(100.0, (temp - 20.0) / 0.7)),
                    ring=(f"{temp:.0f}", "°C"),
                )
            else:
                self._update_row(
                    "temp", "—", "not detected" if not self.gpu.available else "…",
                    0.0, ring=("—", ""),
                )
            row = self.rows.get("temp")
            if row is not None:
                hot = bool(gpu) and gpu["temp"] >= 80
                self.canvas.itemconfigure(
                    row["value"], fill="#ff6b6b" if hot else COL_VALUE
                )

        if self.gpu.name:
            self._set_text(
                self.gpu_label,
                f"{self.gpu.name} · {gpu['temp']:.0f}°C" if gpu else self.gpu.name,
            )
        else:
            self._set_text(self.gpu_label, "")

        if "net" in self.rows:
            counters = psutil.net_io_counters()
            elapsed = max(1e-3, now - self._net_time)
            down = max(0.0, (counters.bytes_recv - self._net_prev.bytes_recv) / elapsed)
            up = max(0.0, (counters.bytes_sent - self._net_prev.bytes_sent) / elapsed)
            self._net_prev, self._net_time = counters, now

            self._update_row(
                "net", f"↓ {fmt_speed(down)}", f"↑ {fmt_speed(up)}",
                self._relative("net", down, 256 * 1024),
                ring=speed_parts(down),
            )
        else:
            self._net_prev = psutil.net_io_counters()
            self._net_time = now

        if "power" in self.rows:
            gpu_w = gpu["power"] if gpu else 0.0
            total_w = self._cpu_watts(cpu) + gpu_w + PLATFORM_W
            if gpu and gpu.get("power"):
                detail = f"GPU {gpu_w:.0f} W"
            elif gpu:
                detail = "CPU + platform"
            else:
                detail = "estimate"
            self._update_row(
                "power", f"≈ {total_w:.0f} W", detail,
                self._relative("power", total_w, 100.0),
                ring=(f"{total_w:.0f}", "W"),
            )

        self.after(max(200, int(float(self.settings["refresh"]) * 1000)), self.refresh)

    @staticmethod
    def _cpu_watts(utilization: float) -> float:
        tdp = float(CPU_TDP_W)
        idle = 0.35 * tdp
        peak = 1.35 * tdp
        return idle + (peak - idle) * (max(0.0, min(100.0, utilization)) / 100.0) ** 0.85

    def _relative(self, key: str, value: float, floor: float) -> float:
        history = self.history.setdefault(key, deque(maxlen=40))
        history.append(value)
        peak = max(max(history), floor)
        return min(100.0, value / peak * 100.0) if peak > 0 else 0.0

    def _update_row(
        self, key: str, value_text: str, detail_text: str, bar_pct: float,
        ring: tuple[str, str] | None = None,
    ) -> None:
        row = self.rows.get(key)
        if row is None:
            return

        if row["kind"] == "ring":
            if ring is not None:
                number, unit = ring
                if unit == "%":
                    self._set_text(row["value"], f"{number}%")
                    self._set_text(row["unit"], "")
                    self.canvas.coords(row["value"], row["cx"], row["cy"])
                else:
                    self._set_text(row["value"], number)
                    self._set_text(row["unit"], unit)
                    self.canvas.coords(
                        row["value"], row["cx"], row["cy"] - 5 * self.scale
                    )
                    self.canvas.coords(
                        row["unit"], row["cx"], row["cy"] + 8 * self.scale
                    )
            self._set_text(row["detail"], detail_text)
        else:
            self._set_text(row["value"], value_text)
            if row["detail"] is not None:
                self._set_text(row["detail"], detail_text)

        self.targets[key] = max(0.0, min(100.0, bar_pct))

    def _set_text(self, item, text: str) -> None:
        if item is None:
            return
        if self.canvas.itemcget(item, "text") != text:
            self.canvas.itemconfigure(item, text=text)

    def _tick_animation(self) -> None:
        dirty = False
        for key, row in self.rows.items():
            target = self.targets.get(key, 0.0)
            shown = self.shown.get(key, 0.0)
            if abs(target - shown) < 0.25:
                shown = target
            else:
                shown += (target - shown) * 0.4
                dirty = True
            self.shown[key] = shown

            if row["ring"] is not None:
                extent = -359.99 * shown / 100.0 if shown > 0.15 else -0.001
                self.canvas.itemconfigure(row["ring"], extent=extent)
                continue

            if row["fill"] is None:
                continue

            width = (row["x2"] - row["x1"]) * shown / 100.0
            if row["last_width"] is None or abs(row["last_width"] - width) >= 0.8:
                row["last_width"] = width
                if width < 1.5:
                    coords = (row["x1"], row["y"], row["x1"], row["y"] + row["h"])
                else:
                    coords = capsule_points(
                        row["x1"], row["y"], row["x1"] + width,
                        row["y"] + row["h"], row["h"] / 2.0,
                    )
                self.canvas.coords(row["fill"], *coords)

        self._animate_job = self.after(45 if dirty else 250, self._tick_animation)


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #

def single_instance_guard():
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}Mutex")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        # Someone double-clicked the file again: ask the running copy to show.
        show = kernel32.OpenEventW(0x0002, False, f"Local\\{APP_NAME}Show")  # EVENT_MODIFY_STATE
        if show:
            kernel32.SetEvent(show)
            kernel32.CloseHandle(show)
        return None
    return handle


def watch_show_event(event_handle, notify) -> None:
    kernel32 = ctypes.windll.kernel32
    while True:
        if kernel32.WaitForSingleObject(event_handle, 250) == 0:
            kernel32.ResetEvent(event_handle)
            notify()


def main() -> int:
    _mutex = single_instance_guard()
    if _mutex is None:
        return 0

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    show_event = ctypes.windll.kernel32.CreateEventW(
        None, False, False, f"Local\\{APP_NAME}Show"
    )

    gpu = GpuSampler()
    gpu.start()
    gpu.set_interval(load_settings()["refresh"])

    events: list[str] = []
    threading.Thread(
        target=watch_show_event, args=(show_event, lambda: events.append("show")),
        name="show-watcher", daemon=True,
    ).start()

    hotkey = HotkeyListener(
        {
            "toggle": (HOTKEY_MODIFIERS, HOTKEY_KEY),
            "topmost": (HOTKEY_MODIFIERS, TOPMOST_KEY),
            "lock": (HOTKEY_MODIFIERS, LOCK_KEY),
        },
        events.append,
    )
    hotkey.start()
    hotkey.registered.wait(1.0)

    app = Widget(gpu, hotkey)

    def poll() -> None:
        while events:
            action = events.pop()
            if action == "toggle":
                app.toggle()
            elif action == "topmost":
                app._toggle_topmost()
            elif action == "lock":
                app._toggle_lock()
            elif action == "show":
                app.show()
        app.after(80, poll)

    app.after(120, poll)
    try:
        app.mainloop()
    finally:
        gpu.stop()
        hotkey.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
