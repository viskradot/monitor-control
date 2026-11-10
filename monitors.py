"""Backend pro ovládání monitorů přes DDC/CI protokol."""

import ctypes
import ctypes.wintypes
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from monitorcontrol import Monitor, PowerMode
from monitorcontrol.vcp.vcp_windows import WindowsVCP

logger = logging.getLogger(__name__)
_DDC_LOCK = threading.Lock()


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


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("DeviceName", ctypes.wintypes.WCHAR * 32),
        ("DeviceString", ctypes.wintypes.WCHAR * 128),
        ("StateFlags", ctypes.wintypes.DWORD),
        ("DeviceID", ctypes.wintypes.WCHAR * 128),
        ("DeviceKey", ctypes.wintypes.WCHAR * 128),
    ]


user32.EnumDisplayDevicesW.argtypes = [
    ctypes.wintypes.LPCWSTR, ctypes.wintypes.DWORD,
    ctypes.POINTER(DISPLAY_DEVICEW), ctypes.wintypes.DWORD,
]
user32.EnumDisplayDevicesW.restype = ctypes.wintypes.BOOL


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
        if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            return True

        rc = info.rcMonitor
        width = rc.right - rc.left
        height = rc.bottom - rc.top
        is_primary = bool(info.dwFlags & MONITORINFOF_PRIMARY)

        device_name = info.szDevice
        device = DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(device)
        identity = ""
        if user32.EnumDisplayDevicesW(device_name, 0, ctypes.byref(device), 1):
            identity = device.DeviceID

        monitors.append({
            "device": device_name,
            "width": width,
            "height": height,
            "primary": is_primary,
            "identity": identity,
            "hmonitor": hmonitor,
        })
        return True

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.wintypes.HMONITOR,
        ctypes.wintypes.HDC,
        ctypes.POINTER(ctypes.wintypes.RECT),
        ctypes.wintypes.LPARAM,
    )
    if not user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0):
        raise OSError("Windows monitor enumeration failed")

    return monitors


@dataclass
class MonitorInfo:
    """Informace o jednom monitoru."""

    index: int
    name: str
    manufacturer: str
    power_on: bool | None
    primary: bool = False
    resolution: str = ""
    display_num: int | None = None
    device: str = ""
    identity: str = ""
    power_observed: bool = False

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
        cache_key = wm["identity"]
        cached_name = cache.get(cache_key)
        name = cached_name or f"Monitor {i + 1}"
        manufacturer = _guess_manufacturer(name) or ""

        result.append(MonitorInfo(
            index=i,
            name=name,
            manufacturer=manufacturer,
            power_on=True if wm["primary"] else None,
            primary=wm["primary"],
            resolution=f"{wm['width']}x{wm['height']}",
            display_num=i + 1,
            device=wm["device"],
            identity=wm["identity"],
        ))

    return result


def _open_monitor(windows_monitor: dict) -> Monitor:
    """Open exactly one physical target under this HMONITOR, never by list index.

    monitorcontrol currently exposes this Windows handle mapping only through
    its platform adapter. Keep that dependency isolated here and test it.
    """
    physical = [Monitor(WindowsVCP(handle, description)) for handle, description
                in WindowsVCP._physical_monitors_from_hmonitor(ctypes.wintypes.HMONITOR(windows_monitor["hmonitor"]))]
    if len(physical) != 1:
        raise OSError("Display has no unique physical monitor target")
    return physical[0]


def get_topology_signature() -> tuple:
    """Cheap Windows-only check; does not send DDC/CI requests."""
    return tuple(sorted((wm["identity"], wm["device"], wm["width"], wm["height"], wm["primary"])
                        for wm in _get_windows_monitors()))


def enrich_monitor_info(
    monitors: list[MonitorInfo], win_monitors: list[dict] | None = None,
    *, refresh_names: bool = False,
) -> list[MonitorInfo]:
    """Slow phase — DDC/CI capabilities + power mode."""
    # Never mutate the model owned by the Tk main thread.
    monitors = [replace(mon) for mon in monitors]
    if win_monitors is None:
        win_monitors = _get_windows_monitors()
    cache = _load_cache()
    updated = False

    for info in monitors:
        info.power_observed = False
        targets = [wm for wm in win_monitors if wm["identity"] == info.identity and info.identity]
        if len(targets) != 1:
            continue
        with _DDC_LOCK:
            try:
                mon = _open_monitor(targets[0])
            except Exception:
                logger.debug("Cannot open monitor %s", info.device, exc_info=True)
                continue
            with mon:
                try:
                    model = None if refresh_names else cache.get(info.identity)
                    if not model:
                        model = mon.get_vcp_capabilities().get("model")
                    if model:
                        info.name = model
                        info.manufacturer = _guess_manufacturer(model) or ""
                        if cache.get(info.identity) != model:
                            cache[info.identity] = model
                            updated = True
                except Exception:
                    logger.debug("Model unavailable for %s", info.device, exc_info=True)
                try:
                    info.power_on = mon.get_power_mode() == PowerMode.on
                    info.power_observed = True
                except Exception:
                    # Silence in standby is not evidence of ON.
                    logger.debug("Power unavailable for %s", info.device, exc_info=True)

    if updated:
        _save_cache(cache)

    return monitors


def set_monitor_power(index: int, turn_on: bool, *, identity: str = "") -> bool:
    """Resolve identity afresh, including primary protection, before every write.

    index is retained for callers/diagnostics only; it never selects hardware.
    """
    if not identity:
        return False
    try:
        with _DDC_LOCK:
            # Waking displays may temporarily reject DDC reads. OFF is sent once;
            # ON is retried with bounded delays and must be confirmed by readback.
            for delay in ((0.3, 0.6, 1.0, 1.5) if turn_on else (0,)):
                targets = [wm for wm in _get_windows_monitors() if wm["identity"] == identity]
                if len(targets) != 1 or (targets[0]["primary"] and not turn_on):
                    logger.warning("Monitor target unavailable/protected: %s", identity)
                    return False
                try:
                    mon = _open_monitor(targets[0])
                    with mon:
                        mon.set_power_mode(PowerMode.on if turn_on else PowerMode.off_soft)
                        if not turn_on:
                            logger.info("OFF requested: %s", identity)
                            return True
                        time.sleep(delay)
                        if mon.get_power_mode() == PowerMode.on:
                            logger.info("ON confirmed: %s", identity)
                            return True
                except Exception:
                    if not turn_on:
                        raise
                    logger.debug("Wake not yet confirmed: %s", identity, exc_info=True)
            logger.warning("Could not confirm ON after bounded retries: %s", identity)
            return False
    except Exception as e:
        logger.warning("Failed to change power for monitor %s: %s", index, e)
        return False
