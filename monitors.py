"""Backend pro ovládání monitorů přes DDC/CI protokol."""

import ctypes
import ctypes.wintypes
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from monitorcontrol import get_monitors, PowerMode

logger = logging.getLogger(__name__)


# --- Cache pro názvy monitorů (DDC/CI capabilities jsou pomalé) ---

CACHE_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "MonitorControl" / "cache.json"


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Failed to load monitor name cache", exc_info=True)
        return {}


def _save_cache(cache: dict):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    except Exception:
        logger.warning("Failed to save monitor name cache", exc_info=True)


# --- Mapování výrobců podle prefixů modelů ---

MANUFACTURER_MAP = {
    "XG": "ASUS",
    "VG": "ASUS",
    "PG": "ASUS",
    "PA": "ASUS",
    "TUF": "ASUS",
    "ROG": "ASUS",
    "27M": "Philips",
    "24M": "Philips",
    "32M": "Philips",
    "272": "Philips",
    "242": "Philips",
    "276": "Philips",
    "328": "Philips",
    "LG": "LG",
    "27G": "LG",
    "34G": "LG",
    "U28": "Samsung",
    "S27": "Samsung",
    "S34": "Samsung",
    "C27": "Samsung",
    "C49": "Samsung",
    "LC": "Samsung",
    "DELL": "Dell",
    "AW": "Dell",
    "S24": "Dell",
    "U27": "Dell",
    "P27": "Dell",
    "XV": "Acer",
    "XB": "Acer",
    "VX": "Acer",
    "BL": "BenQ",
    "EW": "BenQ",
    "PD": "BenQ",
    "EX": "BenQ",
    "XL": "BenQ",
    "GW": "BenQ",
    "MAG": "MSI",
    "MPG": "MSI",
    "MEG": "MSI",
    "G24": "MSI",
    "G27": "MSI",
}


# Prefixes sorted longest-first for greedy matching (avoids e.g. "PA" matching before "PG27")
_SORTED_PREFIXES = sorted(MANUFACTURER_MAP.items(), key=lambda x: len(x[0]), reverse=True)


def _guess_manufacturer(model: str) -> str | None:
    """Guess manufacturer from model name prefix."""
    upper = model.upper()
    for prefix, mfg in _SORTED_PREFIXES:
        if upper.startswith(prefix):
            return mfg
    return None


# --- Windows API pro identifikaci monitorů ---

user32 = ctypes.windll.user32

MONITORINFOF_PRIMARY = 0x00000001


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork", ctypes.wintypes.RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szDevice", ctypes.wintypes.WCHAR * 32),
    ]


# Note: argtypes for EnumDisplayMonitors intentionally omitted — ctypes.windll.user32
# is a process-wide singleton and monitorcontrol library passes 0 (not None) for lprcClip,
# which would fail strict LP_RECT type checking.
user32.GetMonitorInfoW.argtypes = [
    ctypes.wintypes.HMONITOR,
    ctypes.POINTER(MONITORINFOEXW),
]
user32.GetMonitorInfoW.restype = ctypes.wintypes.BOOL


def _get_windows_monitors() -> list[dict]:
    """Získá informace o monitorech z Windows API."""
    monitors = []

    def callback(hmonitor, hdc, lprect, lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(hmonitor, ctypes.byref(info))

        rc = info.rcMonitor
        width = rc.right - rc.left
        height = rc.bottom - rc.top
        is_primary = bool(info.dwFlags & MONITORINFOF_PRIMARY)

        device_name = info.szDevice

        monitors.append({
            "device": device_name,
            "width": width,
            "height": height,
            "primary": is_primary,
        })
        return True

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.wintypes.HMONITOR,
        ctypes.wintypes.HDC,
        ctypes.POINTER(ctypes.wintypes.RECT),
        ctypes.wintypes.LPARAM,
    )
    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)

    return monitors


@dataclass
class MonitorInfo:
    """Informace o jednom monitoru."""

    index: int
    name: str
    manufacturer: str
    power_on: bool
    primary: bool = False
    resolution: str = ""
    display_num: int | None = None

    @property
    def full_name(self) -> str:
        if self.manufacturer:
            return f"{self.manufacturer} {self.name}"
        return self.name


def get_monitors_fast() -> list[MonitorInfo]:
    """Rychlá enumerace — Windows API + cache názvů."""
    win_monitors = _get_windows_monitors()
    cache = _load_cache()
    result = []

    for i, wm in enumerate(win_monitors):
        cache_key = f"{wm['device']}_{wm['width']}x{wm['height']}"
        cached_name = cache.get(cache_key)
        name = cached_name or f"Monitor {i + 1}"
        manufacturer = _guess_manufacturer(name) or ""

        result.append(MonitorInfo(
            index=i,
            name=name,
            manufacturer=manufacturer,
            power_on=True,
            primary=wm["primary"],
            resolution=f"{wm['width']}x{wm['height']}",
            display_num=i + 1,
        ))

    return result


def enrich_monitor_info(monitors: list[MonitorInfo], win_monitors: list[dict] | None = None) -> list[MonitorInfo]:
    """Slow phase — DDC/CI capabilities + power mode."""
    physical_monitors = get_monitors()
    if win_monitors is None:
        win_monitors = _get_windows_monitors()
    cache = _load_cache()
    updated = False

    for i, mon in enumerate(physical_monitors):
        if i >= len(monitors):
            break

        with mon:
            try:
                caps = mon.get_vcp_capabilities()
                model = caps.get("model", None)
                if model:
                    monitors[i].name = model
                    monitors[i].manufacturer = _guess_manufacturer(model) or ""
                    if i < len(win_monitors):
                        wm = win_monitors[i]
                        cache_key = f"{wm['device']}_{wm['width']}x{wm['height']}"
                        if cache.get(cache_key) != model:
                            cache[cache_key] = model
                            updated = True
            except Exception:
                pass

            try:
                power = mon.get_power_mode()
                monitors[i].power_on = power == PowerMode.on
            except Exception:
                monitors[i].power_on = True

    if updated:
        _save_cache(cache)

    return monitors


def set_monitor_power(index: int, turn_on: bool) -> bool:
    """Zapne nebo vypne monitor na daném indexu."""
    try:
        physical_monitors = get_monitors()
        mon = physical_monitors[index]
        with mon:
            if turn_on:
                mon.set_power_mode(PowerMode.on)
            else:
                mon.set_power_mode(PowerMode.off_soft)
        return True
    except Exception as e:
        print(f"Chyba při nastavování napájení monitoru {index}: {e}")
        return False
