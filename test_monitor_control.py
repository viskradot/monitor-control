"""Regression tests; no commands are sent to real monitors."""

import unittest
from dataclasses import replace
from unittest.mock import patch
from settings import AppSettings
from types import SimpleNamespace

import main
import monitors


class PhysicalMonitor:
    def __init__(self, power=None):
        self.power = power
        self.capability_reads = 0
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_vcp_capabilities(self):
        self.capability_reads += 1
        return {"model": "VG-test"}

    def get_power_mode(self):
        if self.power is None:
            raise OSError("Monitor does not respond in standby")
        return self.power

    def set_power_mode(self, power):
        self.writes.append(power)


WINDOWS_MONITOR = {"device": "DISPLAY1", "identity": "panel-a", "hmonitor": 123,
                   "width": 1920, "height": 1080, "primary": False}


class BackendTests(unittest.TestCase):
    def test_physical_mapping_preserves_pointer_sized_hmonitor(self):
        wm = dict(WINDOWS_MONITOR, hmonitor=0x1234567887654321)
        with patch.object(monitors, "WindowsVCP") as adapter:
            mapped = adapter._physical_monitors_from_hmonitor
            mapped.return_value = [(999, "test")]
            with patch.object(monitors, "Monitor", return_value=PhysicalMonitor()):
                monitors._open_monitor(wm)
        self.assertEqual(mapped.call_args.args[0].value, 0x1234567887654321)

    def test_failed_read_preserves_off_and_does_not_mutate_input(self):
        original = monitors.MonitorInfo(0, "VG-test", "ASUS", False, identity="panel-a")
        with patch.object(monitors, "_open_monitor", return_value=PhysicalMonitor()), \
             patch.object(monitors, "_load_cache", return_value={}), \
             patch.object(monitors, "_save_cache"):
            result = monitors.enrich_monitor_info([original], [WINDOWS_MONITOR])
        self.assertFalse(result[0].power_on)
        self.assertIsNot(result[0], original)

    def test_background_read_does_not_change_live_state(self):
        original = monitors.MonitorInfo(0, "VG-test", "ASUS", False, identity="panel-a")
        with patch.object(monitors, "_open_monitor", return_value=PhysicalMonitor(monitors.PowerMode.on)), \
             patch.object(monitors, "_load_cache", return_value={}), \
             patch.object(monitors, "_save_cache"):
            result = monitors.enrich_monitor_info([original], [WINDOWS_MONITOR])
        self.assertTrue(result[0].power_on)
        self.assertFalse(original.power_on)

    def test_cached_model_skips_slow_capabilities_request(self):
        physical = PhysicalMonitor(monitors.PowerMode.on)
        with patch.object(monitors, "_open_monitor", return_value=physical), \
             patch.object(monitors, "_load_cache", return_value={"panel-a": "VG-test"}):
            monitors.enrich_monitor_info([monitors.MonitorInfo(0, "VG-test", "ASUS", True, identity="panel-a")], [WINDOWS_MONITOR])
        self.assertEqual(physical.capability_reads, 0)

    def test_explicit_refresh_revalidates_name_after_monitor_replacement(self):
        physical = PhysicalMonitor(monitors.PowerMode.on)
        with patch.object(monitors, "_open_monitor", return_value=physical), \
             patch.object(monitors, "_load_cache", return_value={"panel-a": "Old monitor"}), \
             patch.object(monitors, "_save_cache"):
            result = monitors.enrich_monitor_info(
                [monitors.MonitorInfo(0, "Old monitor", "", True, identity="panel-a")], [WINDOWS_MONITOR], refresh_names=True,
            )
        self.assertEqual(result[0].name, "VG-test")

    def test_power_resolves_identity_after_reordering(self):
        target = PhysicalMonitor()
        primary = dict(WINDOWS_MONITOR, identity="primary", primary=True)
        with patch.object(monitors, "_get_windows_monitors", return_value=[primary, WINDOWS_MONITOR]), \
             patch.object(monitors, "_open_monitor", return_value=target) as opened:
            self.assertTrue(monitors.set_monitor_power(0, False, identity="panel-a"))
        self.assertEqual(opened.call_args.args[0]["identity"], "panel-a")
        self.assertEqual(target.writes, [monitors.PowerMode.off_soft])

    def test_missing_or_new_primary_target_is_never_turned_off(self):
        for windows in ([], [dict(WINDOWS_MONITOR, primary=True)], [WINDOWS_MONITOR, WINDOWS_MONITOR]):
            with self.subTest(windows=windows), \
                 self.assertLogs(monitors.logger, level="WARNING"), \
                 patch.object(monitors, "_get_windows_monitors", return_value=windows), \
                 patch.object(monitors, "_open_monitor") as opened:
                self.assertFalse(monitors.set_monitor_power(0, False, identity="panel-a"))
                opened.assert_not_called()

    def test_no_identity_never_falls_back_to_index(self):
        with patch.object(monitors, "_open_monitor") as opened:
            self.assertFalse(monitors.set_monitor_power(0, False))
        opened.assert_not_called()

    def test_wake_retries_transient_read_errors_until_on_is_confirmed(self):
        target = PhysicalMonitor()
        with patch.object(monitors, "_get_windows_monitors", return_value=[WINDOWS_MONITOR]), \
             patch.object(monitors, "_open_monitor", return_value=target), \
             patch.object(target, "get_power_mode", side_effect=[OSError("waking"), monitors.PowerMode.on]), \
             patch.object(monitors.time, "sleep"):
            self.assertTrue(monitors.set_monitor_power(0, True, identity="panel-a"))
        self.assertEqual(target.writes, [monitors.PowerMode.on, monitors.PowerMode.on])

    def test_wake_does_not_claim_success_when_on_cannot_be_confirmed(self):
        target = PhysicalMonitor()
        with patch.object(monitors, "_get_windows_monitors", return_value=[WINDOWS_MONITOR]), \
             patch.object(monitors, "_open_monitor", return_value=target), \
             patch.object(monitors.time, "sleep"), \
             self.assertLogs(monitors.logger, level="WARNING"):
            self.assertFalse(monitors.set_monitor_power(0, True, identity="panel-a"))


class PendingThread:
    jobs = []

    def __init__(self, target, args=(), **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.jobs.append(self)

    def run(self):
        self.target(*self.args)


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.thread_patch = patch.object(main.threading, "Thread", PendingThread)
        self.thread_patch.start()
        self.addCleanup(self.thread_patch.stop)
        self.mon = monitors.MonitorInfo(0, "VG-test", "ASUS", True, device="DISPLAY1", identity="panel-a")
        self.fast_patch = patch.object(main, "get_monitors_fast", side_effect=lambda: [replace(self.mon)])
        self.fast_patch.start()
        self.addCleanup(self.fast_patch.stop)
        with patch.object(main.MonitorControlApp, "_setup_tray"), \
             patch.object(main.MonitorControlApp, "_start_services", create=True), \
             patch.object(main, "_get_icon_path", return_value=""):
            self.app = main.MonitorControlApp()
        self.app.withdraw()
        self.addCleanup(self.close_app)
        self.card = self.app.monitor_cards[0]
        PendingThread.jobs.clear()

    def close_app(self):
        # Cancel Tk/CustomTkinter timers before disposing each test window.
        for timer in self.app.tk.call("after", "info"):
            self.app.after_cancel(timer)
        self.app.destroy()

    def click_off(self):
        self.card.switch_var.set("off")
        self.card._on_toggle()

    def finish(self, success):
        with patch.object(main, "set_monitor_power", return_value=success):
            PendingThread.jobs[0].run()
        self.app.update()

    def test_success_updates_model_and_tray_source(self):
        self.click_off()
        self.finish(True)
        self.assertFalse(self.app.monitors_data[0].power_on)
        self.assertEqual(self.card.switch_var.get(), "off")

    def test_pending_toggle_blocks_duplicate_commands(self):
        self.click_off()
        self.card._on_toggle()
        self.assertEqual(len(PendingThread.jobs), 1)
        self.assertEqual(self.card.switch.cget("state"), "disabled")
        self.finish(True)
        self.assertEqual(self.card.switch.cget("state"), "normal")

    def test_late_enrichment_cannot_undo_click(self):
        stale = replace(self.mon)
        self.click_off()
        self.finish(True)
        self.app._apply_enrichment([stale])
        self.assertFalse(self.card.monitor.power_on)
        self.assertEqual(self.card.switch_var.get(), "off")

    def test_failed_write_restores_actual_previous_state(self):
        self.app._window_visible = False
        self.click_off()
        with self.assertLogs(main.logger, level="WARNING"):
            self.finish(False)
        self.assertTrue(self.card.monitor.power_on)
        self.assertEqual(self.card.switch_var.get(), "on")
        self.assertEqual(self.card.switch.cget("state"), "normal")

    def test_refresh_preserves_last_off_state_until_read_finishes(self):
        self.click_off()
        self.finish(True)
        self.app._load_monitors()
        self.assertFalse(self.app.monitor_cards[0].monitor.power_on)

    def test_refresh_is_blocked_while_write_is_in_flight(self):
        self.click_off()
        self.app._load_monitors()
        self.assertIs(self.app.monitor_cards[0], self.card)

    def test_previous_refresh_results_are_discarded(self):
        generation = self.app._load_generation
        self.app._load_monitors()
        self.app._apply_enrichment([replace(self.mon, power_on=False)], generation)
        self.assertTrue(self.app.monitor_cards[0].monitor.power_on)

    def test_tray_uses_same_async_toggle_and_latest_state(self):
        self.click_off()
        self.finish(True)
        PendingThread.jobs.clear()
        self.app._make_tray_toggle("panel-a")(None, None)
        self.app.update()
        self.assertEqual(self.card.switch_var.get(), "on")
        self.assertTrue(self.card.power_pending)
        self.finish(True)
        self.assertTrue(self.card.monitor.power_on)

    def test_primary_monitor_is_protected_from_tray_and_direct_toggle(self):
        self.card.monitor.primary = True
        self.app._make_tray_toggle("panel-a")(None, None)
        self.app.update()
        self.click_off()
        self.assertEqual(PendingThread.jobs, [])
        self.assertEqual(self.card.switch_var.get(), "on")

    def test_unreadable_initial_state_is_not_reported_as_on(self):
        self.card.update_power(None)
        self.app._window_visible = False
        self.assertIn("UNKNOWN", self.card.status_label.cget("text"))
        self.card.switch_var.set("on")
        self.card._on_toggle()
        with self.assertLogs(main.logger, level="WARNING"):
            self.finish(False)
        self.assertIsNone(self.card.monitor.power_on)
        self.assertIn("UNKNOWN", self.card.status_label.cget("text"))

    def test_quit_restores_only_monitors_turned_off_by_this_session(self):
        self.click_off()
        self.finish(True)
        PendingThread.jobs.clear()
        with patch.object(self.app, "_destroy_app", create=True) as destroyed:
            self.app._begin_quit()
            self.assertFalse(destroyed.called)
            with patch.object(main, "set_monitor_power", return_value=True) as power:
                PendingThread.jobs[0].run()
            self.app.update()
            power.assert_called_once_with(0, True, identity="panel-a")
            destroyed.assert_called_once()

    def test_quit_waits_for_pending_off_before_restoring(self):
        self.click_off()
        self.app._begin_quit()
        self.assertEqual(len(PendingThread.jobs), 1)
        self.finish(True)
        self.assertEqual(len(PendingThread.jobs), 2)
        self.assertTrue(self.app._restoring)

    def test_failed_restore_can_cancel_exit_without_losing_ledger(self):
        self.click_off()
        self.finish(True)
        PendingThread.jobs.clear()
        self.app._begin_quit()
        with patch.object(main, "set_monitor_power", return_value=False):
            PendingThread.jobs[0].run()
        with patch.object(main.messagebox, "askyesnocancel", return_value=None), \
             patch.object(self.app, "_destroy_app", create=True) as destroyed:
            self.app.update()
        destroyed.assert_not_called()
        self.assertFalse(self.app._exit_requested)
        self.assertIn("panel-a", self.app._session_off)

    def test_quit_without_session_off_does_not_touch_hardware(self):
        self.card.update_power(False)
        with patch.object(self.app, "_destroy_app", create=True) as destroyed:
            self.app._begin_quit()
        self.assertEqual(PendingThread.jobs, [])
        destroyed.assert_called_once()

    def test_topology_change_refreshes_without_slow_name_queries(self):
        with patch.object(main, "get_topology_signature", create=True, return_value=("new",)), \
             patch.object(self.app, "_load_monitors") as refresh:
            self.app._check_topology()
        refresh.assert_called_once_with(refresh_names=False)

    def test_hotkey_targets_identity_using_shared_async_path(self):
        self.app.settings = AppSettings("Ctrl+Alt+M", "panel-a")
        self.app._trigger_hotkey()
        self.assertTrue(self.card.power_pending)
        self.assertEqual(self.card.switch_var.get(), "off")
        self.finish(True)
        self.assertFalse(self.card.monitor.power_on)

    def test_missing_hotkey_target_does_not_fall_back_to_another_monitor(self):
        self.app.settings = AppSettings("Ctrl+Alt+M", "missing")
        with patch.object(self.app, "_notify_error") as notify:
            self.app._trigger_hotkey()
        self.assertEqual(PendingThread.jobs, [])
        notify.assert_called_once()

    def test_settings_write_failure_rolls_back_native_shortcut(self):
        previous = AppSettings("Ctrl+Alt+M", "panel-a")
        self.app.settings = previous
        with patch.object(self.app.hotkey, "configure") as configure, \
             patch.object(main, "save_settings", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.app._apply_hotkey_settings("Ctrl+Alt+N", "panel-a")
        self.assertEqual(self.app.settings, previous)
        self.assertEqual([call.args[0] for call in configure.call_args_list], ["Ctrl+Alt+N", "Ctrl+Alt+M"])

    def test_tray_distinguishes_pending_requested_and_observed_states(self):
        self.click_off()
        labels = [item.text for item in self.app._build_tray_menu()]
        self.assertIn("ASUS VG-test: TURNING OFF", labels)
        self.finish(True)
        labels = [item.text for item in self.app._build_tray_menu()]
        self.assertIn("ASUS VG-test: OFF (REQUESTED)", labels)
        self.card.update_power(False, observed=True)
        labels = [item.text for item in self.app._build_tray_menu()]
        self.assertIn("ASUS VG-test: OFF", labels)

    def test_settings_captures_key_combination_without_typing_text(self):
        dialog = main.SettingsDialog(self.app)
        self.addCleanup(dialog.destroy)
        self.app.deiconify()
        dialog.deiconify()
        dialog.after(250, dialog.quit)
        dialog.mainloop()
        dialog.shortcut._entry.focus_force()
        dialog.update()
        dialog.shortcut._entry.event_generate("<KeyPress>", keycode=77, state=4 | 0x20000)
        dialog.update()
        self.assertEqual(dialog.shortcut.get(), "Ctrl+Alt+M", msg=f"capture message: {dialog.error_label.cget('text')}; focus: {dialog.focus_get()}")
        dialog.shortcut._entry.event_generate("<KeyPress>", keycode=77, state=4 | 1 | 8)
        dialog.update()
        self.assertEqual(dialog.shortcut.get(), "Ctrl+Shift+M")
        # Pressing/releasing only a modifier never erases a captured combination.
        dialog._capture_hotkey(SimpleNamespace(keycode=17, state=4, keysym="Control_L"))
        self.assertEqual(dialog.shortcut.get(), "Ctrl+Shift+M")
        dialog._capture_hotkey(SimpleNamespace(keycode=0x7B, state=4, keysym="F12"))
        self.assertEqual(dialog.shortcut.get(), "Ctrl+Shift+M")
        self.assertIn("F12", dialog.error_label.cget("text"))
        dialog._clear_hotkey()
        self.assertEqual(dialog.shortcut.get(), "")


if __name__ == "__main__":
    unittest.main()
