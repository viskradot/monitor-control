# Build

## Prerequisites

- Python 3.12+
- pip (comes with Python)
- Windows 10 or 11

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Run from Source

```bash
python main.py
```

## Build Executable

Using the included build script:

```bash
build.bat
```

Or manually:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name MonitorControl main.py
```

Output: `dist/MonitorControl.exe`

## Build Options Explained

- `--onefile` — bundles everything into a single .exe
- `--windowed` — no console window on launch (GUI app)
- `--name MonitorControl` — sets the output filename

## Known Issues

- **Antivirus false positives**: PyInstaller executables are often flagged by AV software. This is a known PyInstaller issue, not malware. Add an exclusion or use the Python source directly.
- **Startup delay**: The --onefile build extracts to a temp directory on each launch, causing a 1-3 second delay. This is normal PyInstaller behavior.
- **Missing DLLs**: If the build fails, ensure all dependencies are installed: `pip install -r requirements.txt`
