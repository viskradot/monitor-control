# Architecture

## File Structure

```
monitor-control/
├── main.py          # GUI application (CustomTkinter + pystray)
├── monitors.py      # Backend: DDC/CI, Windows API, caching
├── hotkeys.py       # Native global hotkey and dedicated Win32 message thread
├── settings.py      # Validated local JSON settings
├── version.py       # Application version
├── requirements.txt # Python dependencies
├── build.bat        # PyInstaller build script
└── docs/            # Documentation
```

## Key Classes

- **`MonitorInfo`** (dataclass in `monitors.py`) — includes display metadata, Windows device interface `identity`, `power_on` and `power_observed`. `index` is only a UI/diagnostic position, never a hardware selector. `power_on=None` means unknown.
- **`MonitorCard`** (CTkFrame in `main.py`) — compact card widget for one monitor with name, badge, status, switch
- **`MonitorControlApp`** (CTk in `main.py`) — main window, manages cards, tray, enrichment

## Data Flow

1. `get_monitors_fast()` — Windows API via `EnumDisplayMonitors` → instant monitor list with resolution + primary flag
2. Cache lookup — restores previously discovered DDC/CI model names
3. UI renders immediately with fast data
4. `enrich_monitor_info()` runs on an independent snapshot in a background thread — startup uses cached names to avoid repeated capabilities queries; explicit Refresh revalidates names to detect replacement monitors
5. Results applied back to UI via `self.after(0, callback)`; old refresh generations and power readings superseded by user commands are discarded

## Threading Model

- **Main thread**: Tkinter event loop, all UI operations
- **Enrichment thread**: DDC/CI capability queries (slow, ~1-3s per monitor)
- **Power toggle thread**: Per-toggle, short-lived, calls `set_monitor_power`
- **Tray thread**: `pystray.Icon.run()` — handles system tray events
- **Hotkey thread**: RegisterHotKey/GetMessage on its own native message queue; only schedules Tk callbacks. Conflicting registrations preserve the previous shortcut.
- **Rule**: All UI updates from non-main threads go through `self.after(0, callback)`
- DDC/CI transactions share a lock, so reads and writes never overlap. A pending toggle disables that monitor's switch and tray action, and temporarily blocks Refresh.
- Window and tray toggles use the same asynchronous path. Successful writes update the shared model; failed writes restore the previous state, including UNKNOWN.
- Refresh preserves the last known state by Windows device identity. Failed power reads preserve that state; they never imply ON. There is no continuous power polling, so manual changes require Refresh.
- Every 2 seconds, inexpensive Windows enumeration checks identity, geometry and primary status. Topology changes and a timer gap over 8 seconds trigger a background refresh; showing the window also refreshes. Resume detection is heuristic, not a dedicated power-event subscription.
- Successful OFF commands enter a session ledger independent of the displayed cards. Normal Quit waits for pending commands and asynchronously restores ledger targets. Confirmed ON removes them. Failed restoration offers Retry, Quit Anyway or Cancel.
- `WindowsVCP._physical_monitors_from_hmonitor` is the isolated private adapter dependency; monitorcontrol is pinned to the tested version. Recheck mapping and pointer sizes before upgrading it.

## Regression Tests

Run `python -m unittest -v` on Windows with the application dependencies installed. Tests exercise real Tk widgets and controlled DDC/CI responses, without changing physical monitor power.

## Design Decisions

- Windows API first for instant UX, DDC/CI is slow (~2-5s for all monitors)
- Sequential numbering #1, #2 instead of Windows device paths (user-friendly)
- Primary monitor always blocked from power toggle (prevents self-lockout)
- Monitor names cached in `%LOCALAPPDATA%` to avoid repeated slow DDC/CI queries
- AppUserModelID set so Windows groups taskbar icon correctly
