"""Monitor Control — DDC/CI monitor power management."""

import ctypes
import os
import tempfile
import threading

import customtkinter as ctk
from PIL import Image, ImageDraw
import pystray

from monitors import (
    MonitorInfo,
    get_monitors_fast,
    enrich_monitor_info,
    set_monitor_power,
)

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
        elif self.switch_var.get() == "on":
            self.status_label.configure(text=f"{dot} ON", text_color=CLR_GREEN)
        else:
            self.status_label.configure(text=f"{dot} OFF", text_color=CLR_RED)

    def update_name(self, name: str, manufacturer: str = ""):
        self.monitor.name = name
        self.monitor.manufacturer = manufacturer
        self.name_label.configure(text=self.monitor.full_name)

    def update_power(self, is_on: bool):
        self.monitor.power_on = is_on
        self.switch_var.set("on" if is_on else "off")
        self._update_status()

    def _on_toggle(self):
        is_on = self.switch_var.get() == "on"
        self._update_status()
        threading.Thread(target=self._do_power_change, args=(is_on,), daemon=True).start()

    def _do_power_change(self, turn_on: bool):
        success = set_monitor_power(self.monitor.index, turn_on)
        if not success:
            self.app.after(0, self._revert_on_error, turn_on)
        else:
            self.app.after(0, self.app._update_tray_menu)

    def _revert_on_error(self, attempted_on: bool):
        self.switch_var.set("off" if attempted_on else "on")
        self._update_status()

        if not self.app._window_visible:
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
        self.switch_var.set("on" if is_on else "off")
        self._update_status()


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

        self._build_ui()
        self._load_monitors()
        self._setup_tray()

        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

    def _calc_window_size(self, count: int) -> str:
        header_h = 56
        footer_h = 40
        cards_h = count * (ROW_HEIGHT + CARD_PAD_Y) + 8
        return f"360x{header_h + cards_h + footer_h}"

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

        self.status_bar = ctk.CTkLabel(
            footer, text="", font=ctk.CTkFont(size=9), text_color=CLR_TEXT_DIM,
        )
        self.status_bar.pack(side="right")

    def _load_monitors(self):
        for child in self.cards_frame.winfo_children():
            child.destroy()
        self.monitor_cards.clear()

        try:
            self.monitors_data = get_monitors_fast()
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
            return

        self.geometry(self._calc_window_size(len(self.monitors_data)))

        for mon in self.monitors_data:
            card = MonitorCard(self.cards_frame, mon, self)
            card.pack(fill="x", padx=2, pady=CARD_PAD_Y // 2)
            self.monitor_cards.append(card)

        count = len(self.monitors_data)
        self.status_bar.configure(text=f"{count} monitor{'s' if count > 1 else ''}")
        self._update_tray_menu()

        threading.Thread(target=self._enrich_async, daemon=True).start()

    def _enrich_async(self):
        enriched = enrich_monitor_info(self.monitors_data)
        self.after(0, self._apply_enrichment, enriched)

    def _apply_enrichment(self, enriched: list[MonitorInfo]):
        for i, mon in enumerate(enriched):
            if i < len(self.monitor_cards):
                card = self.monitor_cards[i]
                if isinstance(card, MonitorCard):
                    card.update_name(mon.name, mon.manufacturer)
                    if not mon.primary:
                        card.update_power(mon.power_on)
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
                state = "ON" if mon.power_on else "OFF"
                items.append(pystray.MenuItem(
                    f"{mon.full_name}: {state}",
                    self._make_tray_toggle(mon.index),
                ))

        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit", self._quit_app))

        return pystray.Menu(*items)

    def _update_tray_menu(self):
        if self.tray_icon:
            self.tray_icon.menu = self._build_tray_menu()

    def _make_tray_toggle(self, index: int):
        def toggle(icon, item):
            for card in self.monitor_cards:
                if isinstance(card, MonitorCard) and card.monitor.index == index:
                    current = card.monitor.power_on
                    new_state = not current
                    success = set_monitor_power(index, new_state)
                    if success:
                        card.monitor.power_on = new_state
                        self.after(0, card.set_power_state, new_state)
                        self.after(0, self._update_tray_menu)
                    break
        return toggle

    def _hide_to_tray(self, icon=None, item=None):
        self._window_visible = False
        self.after(0, self.withdraw)
        self._update_tray_menu()

    def _show_from_tray(self, icon=None, item=None):
        self._window_visible = True
        self.after(0, self._do_show)
        self._update_tray_menu()

    def _do_show(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit_app(self, icon=None, item=None):
        if self.tray_icon:
            self.tray_icon.stop()
        self.after(0, self.destroy)


def main():
    app = MonitorControlApp()
    app.mainloop()


if __name__ == "__main__":
    main()
