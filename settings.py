"""Small, validated local settings file; no network or telemetry."""

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from hotkeys import parse_hotkey

SETTINGS_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "MonitorControl" / "settings.json"
logger = logging.getLogger(__name__)


@dataclass
class AppSettings:
    hotkey: str = ""
    target_identity: str = ""


def load_settings(path: Path = SETTINGS_PATH) -> AppSettings:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return AppSettings()
        hotkey = data.get("hotkey", "")
        target = data.get("target_identity", "")
        if not isinstance(hotkey, str) or not isinstance(target, str):
            return AppSettings()
        parsed = parse_hotkey(hotkey)
        return AppSettings(parsed[0] if parsed else "", target)
    except (OSError, ValueError, TypeError):
        return AppSettings()


def save_settings(settings: AppSettings, path: Path = SETTINGS_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
