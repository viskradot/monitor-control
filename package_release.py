"""Create a shareable ZIP with the EXE, sources and dependency notices."""

import sys
import zipfile
from importlib.metadata import distribution
from pathlib import Path

from version import __version__

ROOT = Path(__file__).resolve().parent
SOURCES = (
    "main.py", "monitors.py", "hotkeys.py", "settings.py", "version.py",
    "test_monitor_control.py", "test_hotkeys.py", "requirements.txt",
    "requirements-build.txt", "build.bat", "package_release.py",
)


def create_release(executable: Path | None = None) -> Path:
    executable = executable or ROOT / "dist" / "MonitorControl.exe"
    if not executable.is_file():
        raise FileNotFoundError("Build dist/MonitorControl.exe first.")
    output = executable.parent / f"MonitorControl-{__version__}-Windows.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(executable, "MonitorControl.exe")
        for name in ("README.md", "LICENSE", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md"):
            archive.write(ROOT / name, name)
        for name in SOURCES:
            archive.write(ROOT / name, f"source/{name}")
        for path in (ROOT / "docs").iterdir():
            if path.is_file() and path.suffix in (".md", ".jpg"):
                archive.write(path, f"docs/{path.name}")
        packages = ("monitorcontrol", "customtkinter", "pystray", "Pillow", "darkdetect", "packaging", "six", "pyinstaller")
        for name in packages:
            dependency = distribution(name)
            for item in dependency.files or ():
                if any(token in item.name.lower() for token in ("license", "copying", "copyright", "ofl")):
                    path = dependency.locate_file(item)
                    if path.is_file():
                        archive.write(path, f"third_party_licenses/{name}/{item.as_posix()}")
            if name == "pystray":
                for item in dependency.files or ():
                    if item.parts[0] == "pystray" and item.suffix == ".py":
                        archive.write(dependency.locate_file(item), f"source/third_party/{item.as_posix()}")
        for name in ("LICENSE.txt", "tcl/tcl8.6/license.terms", "tcl/tk8.6/license.terms"):
            path = Path(sys.base_prefix) / name
            if path.is_file():
                archive.write(path, f"third_party_licenses/runtime/{name}")
        archive.writestr("REBUILDING.txt", """Monitor Control source and rebuild instructions

Use Windows and Python 3.12 or newer. In the source directory:
1. Create and activate your own Python virtual environment.
2. Run: python -m pip install -r requirements-build.txt
3. Run: python -m unittest -v
4. Run: python -m PyInstaller --noconfirm --onefile --windowed --exclude-module numpy --name MonitorControl main.py

The complete installed pystray Python implementation is provided under
source/third_party/pystray. Its LGPL/GPL texts are under third_party_licenses/pystray.
To rebuild with a modified tray library, edit that source and copy its pystray
directory over the pystray directory in your virtual environment's
Lib/site-packages before step 3. The application can then be rebuilt normally;
no signing key, activation or online account is required.

The executable is an unsigned beta. Native driver behavior and DDC compatibility
vary. See README.md for limitations and restoration behavior.
""")
    return output


if __name__ == "__main__":
    print(create_release(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None))
