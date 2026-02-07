# Configuration

## Cache

- **Location**: `%LOCALAPPDATA%\MonitorControl\cache.json`
- **Purpose**: Stores DDC/CI monitor model names to avoid slow re-enumeration
- **Format**: JSON mapping device key → model name
- **Key format**: `{device_name}_{width}x{height}` (e.g., `\\.\DISPLAY1_2560x1440`)
- **Clearing**: Delete `cache.json` to force re-detection

## Application Icon

- **Location**: `%LOCALAPPDATA%\MonitorControl\icon.ico`
- **Generated**: Automatically on first launch (256x256 programmatic icon)
- **Custom icon**: Replace the file — it will be preserved between launches

## AppUserModelID

- **Value**: `MonitorControl.App`
- **Purpose**: Windows uses this to group taskbar icons and show notifications correctly
- **Set via**: `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID`

## Monitor Numbering

- Monitors are numbered sequentially: #1, #2, #3...
- Numbering follows Windows API enumeration order (`EnumDisplayMonitors`)
- Primary monitor is always identified with a "MAIN" badge
- Primary monitor's power toggle is always disabled (BLOCKED status)

## UI Status Labels

- **ON** (green) — monitor is powered on
- **OFF** (red) — monitor is in soft standby
- **BLOCKED** (accent red) — primary monitor, toggle disabled
- **MAIN** — badge on primary monitor card
