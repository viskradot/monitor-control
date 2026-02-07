# Monitor Control

A lightweight Windows desktop utility to turn monitors on/off via the DDC/CI protocol.

## Features

- **Fast async loading** — Windows API detection first, DDC/CI enrichment runs in the background
- **Toggle monitors on/off** via DDC/CI VCP code `0xD6`
- **System tray integration** with quick toggle menu for each monitor
- **Auto-detects** monitor names, resolutions, and manufacturer info
- **Name caching** for instant startup on subsequent launches
- **Primary monitor protection** — the primary display is always blocked from toggling
- **Dark theme** with a compact card-based UI

## Screenshot

![Monitor Control](docs/screenshot.png)

*(Screenshot placeholder)*

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12+ |
| GUI | CustomTkinter |
| Monitor control | monitorcontrol |
| System tray | pystray |
| Image handling | Pillow |
| Windows API | ctypes |

## Requirements

- Windows 10 or 11
- DDC/CI enabled on monitors (toggle via monitor OSD settings)
- Python 3.12+

## Installation

```bash
pip install -r requirements.txt
python main.py
```

## Build

Quick build command:

```bash
pyinstaller --onefile --windowed --name MonitorControl main.py
```

For detailed build instructions, see [docs/BUILD.md](docs/BUILD.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [DDC/CI Protocol](docs/DDC-CI.md)
- [Build & Distribution](docs/BUILD.md)
- [Configuration](docs/CONFIGURATION.md)

## License

This project is licensed under the [MIT License](LICENSE).
