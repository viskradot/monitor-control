"""Monitor Control — DDC/CI monitor power management."""

import ctypes
import os
import tempfile
import threading
import time
import logging
import platform
from logging.handlers import RotatingFileHandler
from dataclasses import replace
from tkinter import messagebox, TclError
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw
import pystray

from hotkeys import NativeHotkey, parse_hotkey, shortcut_from_keypress
from settings import AppSettings, load_settings, save_settings
from version import __version__

from monitors import (
    MonitorInfo,
    get_monitors_fast,
    enrich_monitor_info,
    set_monitor_power,
    get_topology_signature,
)

logger = logging.getLogger(__name__)

# Windows: own AppUserModelID so taskbar shows our icon, not Python
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MonitorControl.App")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Colors
CLR_BG = "#1a1a2e"
CLR_CARD = "#16213e"
CLR_CARD_BORDER = "#233554"
CLR_ACCENT = "#e94560"
CLR_GREEN = "#2ecc71"
CLR_RED = "#e74c3c"
CLR_BLUE = "#3498db"
CLR_TEXT = "#ecf0f1"
CLR_TEXT_DIM = "#7f8c8d"

CARD_PAD_Y = 8
ROW_HEIGHT = 58


def _power_text(mon: MonitorInfo, pending_target: bool | None = None) -> str:
    if pending_target is not None:
        return "TURNING ON" if pending_target else "TURNING OFF"
    if mon.power_on is None:
        return "UNKNOWN"
    state = "ON" if mon.power_on else "OFF"
    return state if mon.power_observed else f"{state} (REQUESTED)"


def _create_app_icon(size: int = 32) -> Image.Image:
    """Minimalist monitor icon — Win11 style."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size

    lw = max(1, int(s * 0.045))
    draw.rounded_rectangle(
        [s * 0.1, s * 0.08, s * 0.9, s * 0.62],
        radius=int(s * 0.05),
        outline=CLR_TEXT,
        width=lw,
    )
    draw.rectangle(
        [s * 0.18, s * 0.16, s * 0.82, s * 0.54],
        fill=CLR_BLUE,
    )
    cx = s * 0.5
    draw.line([(cx, s * 0.62), (cx, s * 0.76)], fill=CLR_TEXT, width=lw)
    draw.rounded_rectangle(
        [s * 0.3, s * 0.76, s * 0.7, s * 0.84],
        radius=int(s * 0.025),
        fill=CLR_TEXT,
    )

    return img


def _get_icon_path() -> str:
    icon_dir = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "MonitorControl")
    os.makedirs(icon_dir, exist_ok=True)
    icon_path = os.path.join(icon_dir, "icon.ico")

    if not os.path.exists(icon_path):
        img = _create_app_icon(256)
        img.save(icon_path, format="ICO", sizes=[(256, 256), (48, 48), (32, 32), (16, 16)])
    return icon_path


class MonitorCard(ctk.CTkFrame):
    """Compact monitor row."""

    def __init__(self, parent, monitor: MonitorInfo, app: "MonitorControlApp"):
        super().__init__(parent, corner_radius=8, border_width=1, height=ROW_HEIGHT)
        self.monitor = monitor
        self.app = app
        self.power_pending = False
        self.power_revision = 0
        self.pack_propagate(False)

        self.configure(fg_color=CLR_CARD, border_color=CLR_CARD_BORDER)

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=14, pady=0)

        left = ctk.CTkFrame(content, fg_color="transparent")
        left.pack(side="left", fill="y", expand=True, anchor="w")
        left.pack_configure(pady=8)

        # Name + badge
        name_row = ctk.CTkFrame(left, fg_color="transparent")
        name_row.pack(anchor="w")

        self.name_label = ctk.CTkLabel(
            name_row,
            text=monitor.full_name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=CLR_TEXT,
        )
        self.name_label.pack(side="left")

        if monitor.primary:
            ctk.CTkLabel(
                name_row,
                text=" MAIN ",
                font=ctk.CTkFont(size=8, weight="bold"),
                fg_color=CLR_ACCENT,
                corner_radius=3,
                text_color="white",
                height=16,
            ).pack(side="left", padx=(6, 0))

        # Detail row: #N + resolution + status
        detail_row = ctk.CTkFrame(left, fg_color="transparent")
        detail_row.pack(anchor="w", pady=(1, 0))

        detail_text = f"#{monitor.display_num}"
        if monitor.resolution:
            detail_text += f"  \u2022  {monitor.resolution}"

        ctk.CTkLabel(
            detail_row,
            text=detail_text,
            font=ctk.CTkFont(size=10),
            text_color=CLR_TEXT_DIM,
        ).pack(side="left")

        self.status_label = ctk.CTkLabel(
            detail_row,
            text="",
            font=ctk.CTkFont(size=10),
        )
        self.status_label.pack(side="left", padx=(8, 0))

        # Switch
        self.switch_var = ctk.StringVar(value="on" if monitor.power_on else "off")
        self.switch = ctk.CTkSwitch(
            content,
            text="",
            variable=self.switch_var,
            onvalue="on",
            offvalue="off",
            command=self._on_toggle,
            width=40,
            height=20,
            switch_width=36,
            switch_height=18,
            progress_color=CLR_GREEN,
            button_color="white",
            fg_color=CLR_CARD_BORDER,
        )
        self.switch.pack(side="right", anchor="center")

        if monitor.primary:
            self.switch.configure(state="disabled")
            self.switch.select()

        self._update_status()

    def _update_status(self):
        dot = "\u25CF"
        if self.monitor.primary:
            self.status_label.configure(text=f"{dot} BLOCKED", text_color=CLR_ACCENT)
        else:
            pending = self.switch_var.get() == "on" if self.power_pending else None
            color = (CLR_BLUE if self.power_pending else CLR_TEXT_DIM if self.monitor.power_on is None
                     else CLR_GREEN if self.monitor.power_on else CLR_RED)
            self.status_label.configure(text=f"{dot} {_power_text(self.monitor, pending)}", text_color=color)

    def update_name(self, name: str, manufacturer: str = ""):
        self.monitor.name = name
        self.monitor.manufacturer = manufacturer
        self.name_label.configure(text=self.monitor.full_name)

    def update_power(self, is_on: bool | None, observed: bool = False):
        self.monitor.power_on = is_on
        self.monitor.power_observed = observed
        self.switch_var.set("on" if is_on else "off")
        self._update_status()

    def _on_toggle(self):
        if self.power_pending or self.app._exit_requested:
            return
        if self.monitor.primary:
            self.switch_var.set("on")
            return
        is_on = self.switch_var.get() == "on"
        self.power_revision += 1
        self.power_pending = True
        self.switch.configure(state="disabled")
        self.app.refresh_btn.configure(state="disabled")
        self._update_status()
        self.app._update_tray_menu()
        threading.Thread(target=self._do_power_change, args=(is_on,), daemon=True).start()

    def _do_power_change(self, turn_on: bool):
        success = set_monitor_power(self.monitor.index, turn_on, identity=self.monitor.identity)
        self.app._post_ui(self._finish_power_change, turn_on, success)

    def _finish_power_change(self, turn_on: bool, success: bool):
        self.power_pending = False
        self.switch.configure(state="disabled" if self.app._exit_requested else "normal")
        if not self.app._exit_requested and not any(card.power_pending for card in self.app.monitor_cards):
            self.app.refresh_btn.configure(state="normal")
        if success:
            self.update_power(turn_on, observed=turn_on)
            self.app._record_power_change(self.monitor, turn_on)
        else:
            self._revert_on_error(turn_on)
        self.app._update_tray_menu()
        if self.app._exit_requested:
            self.app._continue_quit()

    def _revert_on_error(self, attempted_on: bool):
        self.update_power(self.monitor.power_on, self.monitor.power_observed)

        if not self.app._window_visible:
            self.app._notify_error("Failed to change monitor state. Check DDC/CI and the display connection.")
            return

        err = ctk.CTkToplevel(self.app)
        err.title("Error")
        err.geometry("280x100")
        err.resizable(False, False)
        err.transient(self.app)
        err.grab_set()
        err.configure(fg_color=CLR_BG)

        ctk.CTkLabel(
            err,
            text="Failed to change monitor state.\nIs DDC/CI enabled on this monitor?",
            font=ctk.CTkFont(size=11),
            text_color=CLR_TEXT,
        ).pack(pady=(14, 6))

        ctk.CTkButton(
            err, text="OK", command=err.destroy, width=60, height=24,
            fg_color=CLR_BLUE, corner_radius=6, font=ctk.CTkFont(size=11),
        ).pack()

    def set_power_state(self, is_on: bool):
        self.update_power(is_on)


class MonitorControlApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("Monitor Control")
        self.configure(fg_color=CLR_BG)
        self.resizable(False, False)

        self._icon_path = _get_icon_path()
        self.iconbitmap(self._icon_path)

        _icon_img = _create_app_icon(32)
        self._icon_photo = ctk.CTkImage(
            light_image=_icon_img,
            dark_image=_icon_img,
            size=(24, 24),
        )

        self.tray_icon: pystray.Icon | None = None
        self.monitor_cards: list[MonitorCard] = []
        self.monitors_data: list[MonitorInfo] = []
        self._window_visible = True
        self._load_generation = 0
        self._exit_requested = False
        self._restoring = False
        self._closed = False
        self._session_off: dict[str, MonitorInfo] = {}
        self._topology_signature = None
        self._last_topology_check = time.monotonic()
        self._topology_dirty = False
        self._watch_timer = None
        self._settings_dialog = None
        self.settings = load_settings()
        self.hotkey = NativeHotkey(lambda: self._post_ui(self._trigger_hotkey))

        self._build_ui()
        self._load_monitors(refresh_names=False)
        self._setup_tray()
        self._start_services()

        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

    def _calc_window_size(self, count: int) -> str:
        header_h = 56
        footer_h = 40
        cards_h = count * (ROW_HEIGHT + CARD_PAD_Y) + 8
        return f"420x{header_h + cards_h + footer_h}"

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 4))

        ctk.CTkLabel(header, text="", image=self._icon_photo).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            header, text="Monitor Control",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=CLR_TEXT,
        ).pack(side="left")

        ctk.CTkLabel(
            header, text="DDC/CI",
            font=ctk.CTkFont(size=9), text_color=CLR_TEXT_DIM,
        ).pack(side="left", padx=(8, 0), pady=(3, 0))

        ctk.CTkFrame(self, height=1, fg_color=CLR_CARD_BORDER).pack(fill="x", padx=16, pady=(6, 0))

        self.cards_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.cards_frame.pack(fill="both", expand=True, padx=12, pady=6)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=16, pady=(0, 10))

        self.refresh_btn = ctk.CTkButton(
            footer, text="\u21BB  Refresh", command=self._load_monitors,
            width=85, height=24, corner_radius=6,
            fg_color=CLR_CARD_BORDER, hover_color=CLR_ACCENT,
            font=ctk.CTkFont(size=11),
        )
        self.refresh_btn.pack(side="left")

        ctk.CTkButton(
            footer, text="Settings", command=self._show_settings,
            width=70, height=24, corner_radius=6, fg_color=CLR_CARD_BORDER,
            hover_color=CLR_ACCENT, font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(6, 0))

        self.status_bar = ctk.CTkLabel(
            footer, text="", font=ctk.CTkFont(size=9), text_color=CLR_TEXT_DIM,
        )
        self.status_bar.pack(side="right")

    def _load_monitors(self, refresh_names: bool = True):
        if self._exit_requested or any(card.power_pending for card in self.monitor_cards):
            return
        self._load_generation += 1
        previous = {mon.identity: (mon.power_on, mon.power_observed) for mon in self.monitors_data if mon.identity}
        for child in self.cards_frame.winfo_children():
            child.destroy()
        self.monitor_cards.clear()

        try:
            self.monitors_data = get_monitors_fast()
            for mon in self.monitors_data:
                if not mon.primary and mon.identity in previous:
                    mon.power_on, mon.power_observed = previous[mon.identity]
        except Exception as e:
            self.monitors_data = []
            self.status_bar.configure(text=f"Error: {e}")

        if not self.monitors_data:
            ctk.CTkLabel(
                self.cards_frame, text="No monitors found.",
                font=ctk.CTkFont(size=12), text_color=CLR_TEXT_DIM,
            ).pack(pady=20)
            self.geometry("360x160")
            self.status_bar.configure(text="0 monitors")
            self._update_tray_menu()
            return

        self.geometry(self._calc_window_size(len(self.monitors_data)))

        for mon in self.monitors_data:
            card = MonitorCard(self.cards_frame, mon, self)
            card.pack(fill="x", padx=2, pady=CARD_PAD_Y // 2)
            self.monitor_cards.append(card)

        count = len(self.monitors_data)
        self.status_bar.configure(text=f"{count} monitor{'s' if count > 1 else ''}")
        self._update_tray_menu()

        snapshot = [replace(mon) for mon in self.monitors_data]
        threading.Thread(
            target=self._enrich_async,
            args=(snapshot, self._load_generation, refresh_names), daemon=True,
        ).start()

    def _enrich_async(self, snapshot: list[MonitorInfo], generation: int, refresh_names: bool):
        try:
            enriched = enrich_monitor_info(snapshot, refresh_names=refresh_names)
        except Exception:
            logger.exception("Monitor discovery failed")
            return
        self._post_ui(self._apply_enrichment, enriched, generation)

    def _apply_enrichment(self, enriched: list[MonitorInfo], generation: int | None = None):
        if self._exit_requested or (generation is not None and generation != self._load_generation):
            return
        for i, mon in enumerate(enriched):
            if i < len(self.monitor_cards):
                card = self.monitor_cards[i]
                if isinstance(card, MonitorCard):
                    card.update_name(mon.name, mon.manufacturer)
                    if not mon.primary and card.power_revision == 0:
                        card.update_power(mon.power_on, mon.power_observed)
        self._update_tray_menu()

    # --- System Tray ---

    def _setup_tray(self):
        self.tray_icon = pystray.Icon(
            "MonitorControl",
            _create_app_icon(64),
            "Monitor Control",
            self._build_tray_menu(),
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _build_tray_menu(self) -> pystray.Menu:
        items = []

        if self._window_visible:
            items.append(pystray.MenuItem("Hide", self._hide_to_tray, default=True))
        else:
            items.append(pystray.MenuItem("Show", self._show_from_tray, default=True))

        items.append(pystray.Menu.SEPARATOR)

        for mon in self.monitors_data:
            if mon.primary:
                items.append(pystray.MenuItem(
                    f"{mon.full_name} (MAIN)", None, enabled=False,
                ))
            else:
                card = next((card for card in self.monitor_cards if card.monitor.identity == mon.identity), None)
                pending = card.switch_var.get() == "on" if card and card.power_pending else None
                state = _power_text(mon, pending)
                items.append(pystray.MenuItem(
                    f"{mon.full_name}: {state}",
                    self._make_tray_toggle(mon.identity),
                    enabled=not self._exit_requested and bool(mon.identity) and not any(card.monitor.identity == mon.identity and card.power_pending
                                    for card in self.monitor_cards),
                ))

        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Settings", lambda icon, item: self.after(0, self._show_settings), enabled=not self._exit_requested))
        items.append(pystray.MenuItem("Quit", self._quit_app))

        return pystray.Menu(*items)

    def _update_tray_menu(self):
        if self.tray_icon:
            self.tray_icon.menu = self._build_tray_menu()

    def _post_ui(self, callback, *args):
        if self._closed:
            return
        try:
            self.after(0, callback, *args)
        except (RuntimeError, TclError):
            logger.debug("UI callback discarded during shutdown", exc_info=True)

    def _make_tray_toggle(self, identity: str):
        def toggle(icon, item):
            self._post_ui(self._toggle_from_tray, identity)
        return toggle

    def _toggle_from_tray(self, identity: str):
        if self._exit_requested:
            return
        for card in self.monitor_cards:
            if card.monitor.identity == identity and not card.monitor.primary and not card.power_pending:
                card.switch_var.set("off" if card.monitor.power_on else "on")
                card._on_toggle()
                break

    def _hide_to_tray(self, icon=None, item=None):
        self._post_ui(self._do_hide)

    def _do_hide(self):
        self._window_visible = False
        self.withdraw()
        self._update_tray_menu()

    def _show_from_tray(self, icon=None, item=None):
        self._post_ui(self._do_show)

    def _do_show(self):
        self._window_visible = True
        self._update_tray_menu()
        self.deiconify()
        self.lift()
        self.focus_force()
        self._load_monitors(refresh_names=False)

    def _quit_app(self, icon=None, item=None):
        self._post_ui(self._begin_quit)

    def _start_services(self):
        try:
            self._topology_signature = get_topology_signature()
        except Exception:
            logger.debug("Initial topology unavailable", exc_info=True)
        try:
            self.hotkey.configure(self.settings.hotkey)
        except (ValueError, OSError) as exc:
            self._notify_error(f"Global shortcut disabled: {exc}")
        self._watch_timer = self.after(2000, self._check_topology)

    def _trigger_hotkey(self):
        if self._exit_requested or self._closed:
            return
        if self._settings_dialog and self._settings_dialog.winfo_exists():
            return
        identity = self.settings.target_identity
        if not any(mon.identity == identity and not mon.primary for mon in self.monitors_data):
            self._notify_error("Shortcut monitor is unavailable or is now the main display. Select a monitor in Settings.")
            return
        self._toggle_from_tray(identity)

    def _show_settings(self):
        if self._exit_requested:
            return
        if self._settings_dialog and self._settings_dialog.winfo_exists():
            self._settings_dialog.lift()
            return
        self._settings_dialog = SettingsDialog(self)

    def _apply_hotkey_settings(self, shortcut: str, identity: str):
        parsed = parse_hotkey(shortcut)
        normalized = parsed[0] if parsed else ""
        if normalized and not identity:
            raise ValueError("Select a monitor for the shortcut.")
        new_settings = AppSettings(normalized, identity)
        self.hotkey.configure(normalized)
        try:
            save_settings(new_settings)
        except OSError:
            self.hotkey.configure(self.settings.hotkey)
            raise
        self.settings = new_settings

    def _copy_diagnostics(self):
        lines = [f"Monitor Control {__version__}", platform.platform(),
                 f"Python {platform.python_version()}", f"Shortcut: {self.hotkey.shortcut or 'disabled'}"]
        for mon in self.monitors_data:
            lines.append(f"#{mon.display_num}: {mon.full_name}; {mon.resolution}; "
                         f"primary={mon.primary}; power={mon.power_on}; observed={mon.power_observed}")
        lines.append("Identity mappings and command failures are recorded in the local log.")
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))

    def _check_topology(self):
        if self._closed:
            return
        now = time.monotonic()
        resumed = now - self._last_topology_check > 8
        self._last_topology_check = now
        try:
            signature = get_topology_signature()
            if signature != self._topology_signature or resumed:
                self._topology_signature = signature
                self._topology_dirty = True
            if self._topology_dirty and not self._exit_requested and not any(c.power_pending for c in self.monitor_cards):
                self._topology_dirty = False
                self._load_monitors(refresh_names=False)
        except Exception:
            logger.debug("Topology check failed", exc_info=True)
        self._watch_timer = self.after(2000, self._check_topology)

    def _record_power_change(self, mon: MonitorInfo, is_on: bool):
        if is_on:
            self._session_off.pop(mon.identity, None)
        elif mon.identity:
            self._session_off[mon.identity] = replace(mon)

    def _notify_error(self, text: str):
        logger.warning(text)
        self.status_bar.configure(text="Command failed")
        if self.tray_icon:
            try:
                self.tray_icon.notify(text, "Monitor Control")
            except Exception:
                logger.debug("Tray notification unavailable", exc_info=True)

    def _begin_quit(self):
        if self._exit_requested:
            return
        self._exit_requested = True
        if self._settings_dialog and self._settings_dialog.winfo_exists():
            self._settings_dialog.destroy()
        self._load_generation += 1
        self.refresh_btn.configure(state="disabled")
        for card in self.monitor_cards:
            card.switch.configure(state="disabled")
        self.status_bar.configure(text="Restoring monitors...")
        self._update_tray_menu()
        self._continue_quit()

    def _continue_quit(self):
        if self._restoring or any(c.power_pending for c in self.monitor_cards):
            return
        if not self._session_off:
            self._destroy_app()
            return
        self._restoring = True
        snapshot = list(self._session_off.values())
        threading.Thread(target=self._restore_monitors, args=(snapshot,), daemon=True).start()

    def _restore_monitors(self, snapshot: list[MonitorInfo]):
        results = [(mon.identity, set_monitor_power(mon.index, True, identity=mon.identity)) for mon in snapshot]
        self._post_ui(self._finish_restore, results)

    def _finish_restore(self, results: list[tuple[str, bool]]):
        self._restoring = False
        for identity, success in results:
            if success:
                self._session_off.pop(identity, None)
                for card in self.monitor_cards:
                    if card.monitor.identity == identity:
                        card.update_power(True, observed=True)
        if not self._session_off:
            self._destroy_app()
            return
        self.deiconify()
        self._window_visible = True
        choice = messagebox.askyesnocancel(
            "Monitor restoration failed",
            "Could not confirm that all monitors are ON.\n"
            "Check their power buttons and connections.\n\n"
            "Yes: Retry\nNo: Quit anyway\nCancel: Keep running",
            parent=self,
        )
        if choice is True:
            self._continue_quit()
        elif choice is False:
            self._destroy_app()
        else:
            self._exit_requested = False
            self.refresh_btn.configure(state="normal")
            for card in self.monitor_cards:
                card.switch.configure(state="disabled" if card.monitor.primary else "normal")
            self.status_bar.configure(text="Restore failed; still running")
            self._update_tray_menu()

    def _destroy_app(self):
        self._closed = True
        self.hotkey.close()
        if self._watch_timer:
            self.after_cancel(self._watch_timer)
        if self.tray_icon:
            self.tray_icon.stop()
        self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    """One shortcut, one explicitly selected secondary display."""

    def __init__(self, app: MonitorControlApp):
        super().__init__(app)
        self.app = app
        self.title("Settings")
        self.geometry("420x300")
        self.resizable(False, False)
        self.configure(fg_color=CLR_BG)
        self.transient(app)
        self.grab_set()
        ctk.CTkLabel(self, text="Global shortcut", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(self, text="Click the field, then press your shortcut.", font=ctk.CTkFont(size=11), text_color=CLR_TEXT_DIM).pack(anchor="w", padx=20)
        shortcut_row = ctk.CTkFrame(self, fg_color="transparent")
        shortcut_row.pack(fill="x", padx=20, pady=(8, 10))
        self.shortcut_var = ctk.StringVar(value=app.settings.hotkey)
        self.shortcut = ctk.CTkEntry(shortcut_row, textvariable=self.shortcut_var, state="readonly", width=310)
        self.shortcut.pack(side="left", fill="x", expand=True)
        self.shortcut.bind("<KeyPress>", self._capture_hotkey)
        self.shortcut.bind("<FocusIn>", self._capture_hint)
        ctk.CTkButton(shortcut_row, text="Clear", command=self._clear_hotkey, width=60, fg_color=CLR_CARD_BORDER).pack(side="right", padx=(8, 0))
        self.targets = {f"#{mon.display_num}  {mon.full_name}": mon.identity for mon in app.monitors_data if not mon.primary and mon.identity}
        if app.settings.target_identity and app.settings.target_identity not in self.targets.values():
            self.targets["Saved monitor (unavailable)"] = app.settings.target_identity
        selected = next((name for name, identity in self.targets.items() if identity == app.settings.target_identity), next(iter(self.targets), "No secondary monitor"))
        self.target_var = ctk.StringVar(value=selected)
        self.target = ctk.CTkOptionMenu(self, values=list(self.targets) or ["No secondary monitor"], variable=self.target_var, width=380)
        self.target.pack(padx=20, pady=(0, 8))
        self.error_label = ctk.CTkLabel(self, text="", text_color=CLR_RED, wraplength=380, height=44, font=ctk.CTkFont(size=11))
        self.error_label.pack(padx=20)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=8)
        ctk.CTkButton(buttons, text="Copy diagnostics", command=self._copy, width=130, fg_color=CLR_CARD_BORDER).pack(side="left")
        ctk.CTkButton(buttons, text="Save", command=self._save, width=80, fg_color=CLR_BLUE).pack(side="right")
        ctk.CTkButton(buttons, text="Cancel", command=self.destroy, width=70, fg_color=CLR_CARD_BORDER).pack(side="right", padx=8)

    def _copy(self):
        self.app._copy_diagnostics()
        self.error_label.configure(text="Diagnostics copied.", text_color=CLR_GREEN)

    def _capture_hint(self, event=None):
        self.error_label.configure(text="Press Ctrl and/or Alt with a key. Shift is optional.", text_color=CLR_TEXT_DIM)

    def _capture_hotkey(self, event):
        if event.keysym in ("Tab", "ISO_Left_Tab"):
            return None
        if event.keysym == "Escape":
            self.target.focus_set()
            return "break"
        if event.keysym in ("BackSpace", "Delete") and not event.state & (4 | 0x20000):
            self._clear_hotkey()
            return "break"
        try:
            shortcut = shortcut_from_keypress(event.keycode, event.state)
        except ValueError as exc:
            self.error_label.configure(text=str(exc), text_color=CLR_RED)
            return "break"
        if shortcut:
            self.shortcut_var.set(shortcut)
            self.error_label.configure(text="Shortcut captured. Click Save to apply.", text_color=CLR_GREEN)
        return "break"

    def _clear_hotkey(self):
        self.shortcut_var.set("")
        self.error_label.configure(text="Shortcut disabled. Click Save to apply.", text_color=CLR_TEXT_DIM)

    def _save(self):
        try:
            self.app._apply_hotkey_settings(self.shortcut.get(), self.targets.get(self.target_var.get(), ""))
        except (ValueError, OSError) as exc:
            self.error_label.configure(text=str(exc), text_color=CLR_RED)
            return
        self.destroy()


def main():
    log_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "MonitorControl"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_dir / "monitor-control.log", maxBytes=250_000, backupCount=1, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
    except OSError:
        pass
    app = MonitorControlApp()
    app.mainloop()


if __name__ == "__main__":
    main()
