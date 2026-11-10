# Configuration

## Cache

- **Location**: `%LOCALAPPDATA%\MonitorControl\cache.json`
- **Purpose**: Stores DDC/CI monitor model names to avoid slow re-enumeration
- **Format**: JSON mapping device key → model name
- **Key format**: Windows monitor device interface identity, obtained through EnumDisplayDevicesW
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

- **ON** (green) / **OFF** (red) — last successful power reading, not continuously polled
- **ON/OFF (REQUESTED)** — last accepted command, without current physical-state confirmation
- **TURNING ON / TURNING OFF** — asynchronous command in progress
- **UNKNOWN** — no reliable power state available
- **BLOCKED** (accent red) — primary monitor, toggle disabled
- **MAIN** — badge on primary monitor card

## Global shortcut

Settings stores an optional global shortcut and the selected secondary monitor's identity in
`%LOCALAPPDATA%\MonitorControl\settings.json`. The initial shortcut is disabled.

Use Ctrl and/or Alt, optionally Shift, plus A-Z, 0-9 or F1-F24. F12 is reserved and rejected.
Click the shortcut field and press the combination, for example Ctrl+Alt+M; it is captured automatically. Click Save to apply it. Use Clear (or Backspace/Delete in the field) and Save to disable it. Tab moves focus and Escape leaves the field. Conflicts do not replace the previous shortcut.
The hotkey uses the same asynchronous power path as the window/tray and is suspended while Settings is open.
If the target is disconnected, has changed identity or is now primary, the shortcut will not select another display.

## Local log

`%LOCALAPPDATA%\MonitorControl\monitor-control.log`, limited to approximately 250 KB plus one rotated file.
Logs stay local and may contain display identifiers. Settings → Copy diagnostics copies a short summary you can review before sharing.
