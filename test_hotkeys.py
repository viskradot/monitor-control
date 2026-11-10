import ctypes
import tempfile
import threading
import unittest
from pathlib import Path

from hotkeys import NativeHotkey, parse_hotkey, shortcut_from_keypress
from settings import AppSettings, load_settings, save_settings


class HotkeyTests(unittest.TestCase):
    def test_key_capture_uses_windows_keys_and_modifiers(self):
        self.assertEqual(shortcut_from_keypress(77, 4 | 0x20000), "Ctrl+Alt+M")
        self.assertEqual(shortcut_from_keypress(0x78, 4 | 1), "Ctrl+Shift+F9")
        self.assertEqual(shortcut_from_keypress(49, 4 | 0x20000 | 1), "Ctrl+Alt+Shift+1")
        self.assertIsNone(shortcut_from_keypress(17, 4))
        with self.assertRaises(ValueError):
            shortcut_from_keypress(0x7B, 4)
        with self.assertRaises(ValueError):
            shortcut_from_keypress(77, 0)

    def test_lock_keys_do_not_add_alt_to_captured_shortcut(self):
        for locks in (0, 8, 2, 32, 8 | 2 | 32):
            with self.subTest(locks=locks):
                self.assertEqual(shortcut_from_keypress(77, 4 | 1 | locks), "Ctrl+Shift+M")
                self.assertEqual(shortcut_from_keypress(77, 4 | 0x20000 | locks), "Ctrl+Alt+M")

    def test_normalization_and_key_codes(self):
        self.assertEqual(parse_hotkey("shift+ctrl+F9"), ("Ctrl+Shift+F9", 6, 0x78))
        self.assertEqual(parse_hotkey("ctrl+alt+m"), ("Ctrl+Alt+M", 3, 77))
        self.assertIsNone(parse_hotkey(""))

    def test_invalid_or_reserved_keys_are_rejected(self):
        for value in ("M", "Shift+M", "Ctrl+F12", "Win+M", "Ctrl+Ctrl+M", "Ctrl+F25", "Ctrl+Alt+"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_hotkey(value)

    def test_native_message_is_delivered_and_registration_is_released(self):
        delivered = threading.Event()
        listener = NativeHotkey(delivered.set)
        self.addCleanup(listener.close)
        listener.configure("Ctrl+Alt+Shift+F23")
        ctypes.windll.user32.PostThreadMessageW(listener.thread_id, 0x312, 1, 0)
        self.assertTrue(delivered.wait(2))
        listener.close()
        other = NativeHotkey(lambda: None)
        self.addCleanup(other.close)
        other.configure("Ctrl+Alt+Shift+F23")

    def test_conflict_preserves_previously_working_shortcut(self):
        first = NativeHotkey(lambda: None)
        second = NativeHotkey(lambda: None)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        first.configure("Ctrl+Alt+Shift+F22")
        second.configure("Ctrl+Alt+Shift+F23")
        with self.assertRaises(OSError):
            first.configure("Ctrl+Alt+Shift+F23")
        self.assertEqual(first.shortcut, "Ctrl+Alt+Shift+F22")


class SettingsTests(unittest.TestCase):
    def test_settings_round_trip_and_disabled_shortcut(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "settings.json"
            settings = AppSettings("Ctrl+Alt+M", "panel-a")
            save_settings(settings, path)
            self.assertEqual(load_settings(path), settings)
            save_settings(AppSettings(), path)
            self.assertEqual(load_settings(path), AppSettings())

    def test_invalid_file_uses_safe_defaults(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "settings.json"
            for data in ("[]", "invalid", '{"hotkey": 12}', '{"hotkey":"Ctrl+F12"}'):
                path.write_text(data)
                self.assertEqual(load_settings(path), AppSettings())


if __name__ == "__main__":
    unittest.main()
