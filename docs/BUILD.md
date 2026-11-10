# Build

## Prerequisites

- Python 3.12+
- pip (comes with Python)
- Windows 10 or 11

## Install Dependencies

```bash
python -m pip install -r requirements.txt
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
python -m pip install -r requirements-build.txt
python -m unittest -v
python -m PyInstaller --noconfirm --onefile --windowed --exclude-module numpy --name MonitorControl main.py
python package_release.py
```

Output: `dist/MonitorControl.exe`

Share `dist/MonitorControl-0.1.0-beta.3-Windows.zip`, which also includes the
application source, dependency license texts, pystray source, and rebuild instructions.
The build uses the tested dependency versions pinned in the requirements files.
`--exclude-module numpy` avoids bundling an optional, unused Pillow integration from a developer's global environment.
The EXE is an unsigned beta. Test it on the target system before relying on monitor restoration.

## Build Options Explained

- `--onefile` — bundles everything into a single .exe
- `--windowed` — no console window on launch (GUI app)
- `--name MonitorControl` — sets the output filename

## Known Issues

- **Unsigned executable warnings**: A self-built beta has no publisher signature. Users can inspect the source and build it themselves.
- **Startup delay**: The --onefile build extracts to a temp directory on each launch, causing a 1-3 second delay. This is normal PyInstaller behavior.
- **Missing DLLs**: If the build fails, ensure all dependencies are installed: `pip install -r requirements.txt`
