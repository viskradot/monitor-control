# Monitor Control — Project Rules

## UI / UX
- All UI text must be in English
- Status labels in CAPS: ON, OFF, BLOCKED, MAIN
- No countdown timer — instant toggle
- Primary monitor is always BLOCKED (cannot be toggled off)
- Sequential monitor numbering: #1, #2 (not Windows device path)

## Architecture
- Async loading pattern: Windows API first (instant), DDC/CI enrichment in background thread
- Cache monitor names in `%LOCALAPPDATA%\MonitorControl\cache.json`
- All cross-thread UI updates must go through `self.after(0, callback)` — never access Tkinter from non-main thread
- Power toggle runs in a short-lived daemon thread

## Code Style
- Python 3.12+ (use `X | Y` union syntax, not `Union[X, Y]`)
- Backend logic in `monitors.py`, GUI in `main.py`
- Color constants prefixed with `CLR_` defined at module level
- Dataclass `MonitorInfo` is the shared data model between backend and GUI

## Build
- PyInstaller: `--onefile --windowed --name MonitorControl`
- Build script: `build.bat`
