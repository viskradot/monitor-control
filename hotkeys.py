"""Optional Windows global shortcut with its own native message queue."""

import ctypes
import ctypes.wintypes as wt
import logging
import threading

logger = logging.getLogger(__name__)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
_user32.RegisterHotKey.restype = wt.BOOL
_user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wt.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
_user32.GetMessageW.restype = ctypes.c_int
_user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
_user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.PostThreadMessageW.restype = wt.BOOL
_kernel32.GetCurrentThreadId.restype = wt.DWORD


def parse_hotkey(value: str) -> tuple[str, int, int] | None:
    """Accept Ctrl/Alt/Shift + A-Z, 0-9 or F1-F24 (except reserved F12)."""
    if not value.strip():
        return None
    parts = [part.strip().upper() for part in value.split("+")]
    modifiers, key = parts[:-1], parts[-1]
    bits = {"CTRL": 2, "ALT": 1, "SHIFT": 4}
    if (not modifiers or len(set(modifiers)) != len(modifiers)
            or any(mod not in bits for mod in modifiers)
            or not any(mod in modifiers for mod in ("CTRL", "ALT"))):
        raise ValueError("Use Ctrl and/or Alt, optionally Shift, plus a letter, digit or function key.")
    if len(key) == 1 and key in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        vk = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24 and int(key[1:]) != 12:
        vk = 0x70 + int(key[1:]) - 1
        key = f"F{int(key[1:])}"
    else:
        raise ValueError("Use A-Z, 0-9 or F1-F24. F12 is reserved by Windows.")
    ordered = [mod.title() for mod in ("CTRL", "ALT", "SHIFT") if mod in modifiers]
    return ("+".join([*ordered, key]), sum(bits[mod] for mod in modifiers), vk)


def shortcut_from_keypress(keycode: int, state: int) -> str | None:
    """Convert a Windows Tk KeyPress to the same format used by RegisterHotKey.

    Use virtual key codes, not keysyms: Shift+1 may have keysym exclam.
    Windows Tk uses 0x20000 for Alt. Mod1 (0x8) is NumLock here,
    unlike X11; treating it as Alt silently corrupts captured shortcuts.
    """
    if keycode in (16, 17, 18, 160, 161, 162, 163, 164, 165):
        return None
    if keycode in (91, 92) or state & 0x40:
        raise ValueError("Windows-key shortcuts are not supported.")
    modifiers = []
    if state & 4:
        modifiers.append("Ctrl")
    if state & 0x20000:
        modifiers.append("Alt")
    if state & 1:
        modifiers.append("Shift")
    if 65 <= keycode <= 90 or 48 <= keycode <= 57:
        key = chr(keycode)
    elif 0x70 <= keycode <= 0x87:
        key = f"F{keycode - 0x70 + 1}"
    else:
        raise ValueError("Use Ctrl and/or Alt plus a letter, digit or function key.")
    parsed = parse_hotkey("+".join([*modifiers, key]))
    return parsed[0]


class _Binding:
    def __init__(self, parsed, callback):
        self.parsed = parsed
        self.callback = callback
        self.thread_id = 0
        self.error = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._listen, daemon=True, name="MonitorControlHotkey")

    def _listen(self):
        registered = False
        try:
            self.thread_id = _kernel32.GetCurrentThreadId()
            msg = wt.MSG()
            # Ensure PostThreadMessage has a queue even before GetMessage starts.
            _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            registered = bool(_user32.RegisterHotKey(None, 1, self.parsed[1] | 0x4000, self.parsed[2]))
            if not registered:
                self.error = OSError(ctypes.get_last_error(), "Shortcut is unavailable or already in use.")
                return
            self.ready.set()
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x312 and msg.wParam == 1:
                    try:
                        self.callback()
                    except Exception:
                        logger.exception("Hotkey callback failed")
        except Exception as exc:
            self.error = exc
        finally:
            if registered:
                _user32.UnregisterHotKey(None, 1)
            self.ready.set()

    def close(self):
        if self.thread_id and self.thread.is_alive():
            _user32.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
            self.thread.join(timeout=2)


class NativeHotkey:
    """Configure on the UI thread; callbacks run on the native listener thread."""

    def __init__(self, callback):
        self.callback = callback
        self._binding = None
        self.shortcut = ""

    @property
    def thread_id(self):
        return self._binding.thread_id if self._binding else 0

    def configure(self, value: str):
        parsed = parse_hotkey(value)
        normalized = parsed[0] if parsed else ""
        if normalized == self.shortcut:
            return
        candidate = None
        if parsed:
            candidate = _Binding(parsed, self.callback)
            candidate.thread.start()
            if not candidate.ready.wait(2):
                candidate.close()
                raise OSError("Shortcut registration timed out.")
            if candidate.error:
                candidate.close()
                raise candidate.error
        previous = self._binding
        self._binding = candidate
        self.shortcut = normalized
        if previous:
            previous.close()

    def close(self):
        if self._binding:
            self._binding.close()
            self._binding = None
        self.shortcut = ""
