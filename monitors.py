"""Backend pro ovládání monitorů přes DDC/CI protokol."""

import ctypes
import ctypes.wintypes
import json
import os
from dataclasses import dataclass
from pathlib import Path

from monitorcontrol import get_monitors, PowerMode


# --- Cache pro názvy monitorů (DDC/CI capabilities jsou pomalé) ---

CACHE_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "MonitorControl" / "cache.json"


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    except Exception:
        pass


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


def _guess_manufacturer(model: str) -> str | None:
    """Odhadne výrobce z názvu modelu."""
    upper = model.upper()
    # Zkusit delší prefixy nejdřív
    for prefix_len in (3, 2):
        for prefix, mfg in MANUFACTURER_MAP.items():
            if len(prefix) == prefix_len and upper.startswith(prefix):
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


def enrich_monitor_info(monitors: list[MonitorInfo]) -> list[MonitorInfo]:
    """Pomalá fáze — DDC/CI capabilities + power mode."""
    physical_monitors = get_monitors()
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
