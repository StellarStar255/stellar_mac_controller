import ctypes as C
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from global_shortcut import CarbonHotKey, GlobalShortcut, SIGNATURE


class Function:
    def __init__(self, action): self.action = action
    def __call__(self, *args): return self.action(*args)


class Carbon:
    def __init__(self, registration_status=0):
        self.removed = self.unregistered = 0
        self.GetApplicationEventTarget = Function(lambda: 1)
        self.InstallEventHandler = Function(self.install)
        self.RegisterEventHotKey = Function(self.register)
        self.RemoveEventHandler = Function(self.remove)
        self.UnregisterEventHotKey = Function(self.unregister)
        self.GetEventKind = Function(lambda event: event)
        self.GetEventParameter = Function(self.parameter)
        self.registration_status = registration_status

    def install(self, target, callback, count, types, data, output):
        output._obj.value = 2
        return 0

    def register(self, code, modifiers, identity, target, options, output):
        if not self.registration_status: output._obj.value = 3
        return self.registration_status

    def remove(self, handler):
        self.removed += 1
        return 0

    def unregister(self, key):
        self.unregistered += 1
        return 0

    def parameter(self, event, name, kind, actual_type, size, actual_size, output):
        output._obj.signature, output._obj.id = SIGNATURE, 1
        return 0


class GlobalHotKeyTests(unittest.TestCase):
    def test_native_event_remembers_background_before_app_activation(self):
        app = Mock()
        app.isActive.return_value = False
        app.respondsToSelector_.return_value = True
        controller = SimpleNamespace(pressed=Mock())
        module = SimpleNamespace(NSApplication=SimpleNamespace(sharedApplication=lambda:app))
        with patch.dict('sys.modules', {'AppKit':module}):
            GlobalShortcut.native_pressed(controller)
        app.activate.assert_called_once_with()
        controller.pressed.emit.assert_called_once_with(True)

    def test_queued_background_hotkey_summons_instead_of_toggling(self):
        window = Mock()
        window.isActiveWindow.return_value = True
        window.isVisible.return_value = True
        window.isMinimized.return_value = False
        window.mini = False
        controller = SimpleNamespace(active=True, application=SimpleNamespace(main_window=window), tray=Mock())
        GlobalShortcut.activate(controller, background=True)
        controller.tray.show_window.assert_called_once_with()
        window.enter_mini.assert_not_called()

    def test_conflict_cleans_handler_without_claiming_the_key(self):
        library = Carbon(registration_status=-9878)
        hotkey = CarbonHotKey(lambda: None, library=library)
        self.assertEqual(hotkey.start(), -9878)
        self.assertFalse(hotkey.key.value)
        self.assertEqual(library.removed, 1)
        hotkey.close()
        self.assertEqual(library.removed, 1)

    def test_holding_key_fires_once_until_release_and_cleanup_is_idempotent(self):
        calls = []
        library = Carbon()
        hotkey = CarbonHotKey(lambda: calls.append(1), library=library)
        self.assertEqual(hotkey.start(), 0)
        hotkey.handle(None, 5, None)
        hotkey.handle(None, 5, None)
        self.assertEqual(len(calls), 1)
        hotkey.handle(None, 6, None)
        hotkey.handle(None, 5, None)
        self.assertEqual(len(calls), 2)
        hotkey.close()
        hotkey.close()
        self.assertEqual((library.removed, library.unregistered), (1, 1))
