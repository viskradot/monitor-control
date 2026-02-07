# Architecture

## File Structure

```
monitor-control/
├── main.py          # GUI application (CustomTkinter + pystray)
├── monitors.py      # Backend: DDC/CI, Windows API, caching
├── requirements.txt # Python dependencies
├── build.bat        # PyInstaller build script
└── docs/            # Documentation
```

## Key Classes

- **`MonitorInfo`** (dataclass in `monitors.py`) — holds `index`, `name`, `manufacturer`, `power_on`, `primary`, `resolution`, `display_num`
- **`MonitorCard`** (CTkFrame in `main.py`) — compact card widget for one monitor with name, badge, status, switch
- **`MonitorControlApp`** (CTk in `main.py`) — main window, manages cards, tray, enrichment

## Data Flow

1. `get_monitors_fast()` — Windows API via `EnumDisplayMonitors` → instant monitor list with resolution + primary flag
2. Cache lookup — restores previously discovered DDC/CI model names
3. UI renders immediately with fast data
4. `enrich_monitor_info()` runs in background thread — DDC/CI capabilities + power state
5. Results applied back to UI via `self.after(0, callback)`

## Threading Model

- **Main thread**: Tkinter event loop, all UI operations
- **Enrichment thread**: DDC/CI capability queries (slow, ~1-3s per monitor)
- **Power toggle thread**: Per-toggle, short-lived, calls `set_monitor_power`
- **Tray thread**: `pystray.Icon.run()` — handles system tray events
- **Rule**: All UI updates from non-main threads go through `self.after(0, callback)`

## Design Decisions

- Windows API first for instant UX, DDC/CI is slow (~2-5s for all monitors)
- Sequential numbering #1, #2 instead of Windows device paths (user-friendly)
- Primary monitor always blocked from power toggle (prevents self-lockout)
- Monitor names cached in `%LOCALAPPDATA%` to avoid repeated slow DDC/CI queries
- AppUserModelID set so Windows groups taskbar icon correctly
