"""macOS system-wide Command-Shift-M, owned by the GUI process only."""
import ctypes as C
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from i18n import tr


def fourcc(value):
    return int.from_bytes(value.encode('ascii'), 'big')


class EventType(C.Structure):
    _fields_ = [('eventClass', C.c_uint32), ('eventKind', C.c_uint32)]


class HotKeyID(C.Structure):
    _fields_ = [('signature', C.c_uint32), ('id', C.c_uint32)]


CALLBACK = C.CFUNCTYPE(C.c_int32, C.c_void_p, C.c_void_p, C.c_void_p)
SIGNATURE = fourcc('SMCT')


class CarbonHotKey:
    def __init__(self, pressed, library=None):
        self.library = library or C.CDLL('/System/Library/Frameworks/Carbon.framework/Carbon')
        self.pressed = pressed
        self.key = C.c_void_p()
        self.handler = C.c_void_p()
        self.down = False
        self.callback = CALLBACK(self.handle)
        signatures = {
            'GetApplicationEventTarget': (C.c_void_p, []),
            'InstallEventHandler': (C.c_int32, [C.c_void_p, CALLBACK, C.c_ulong, C.POINTER(EventType), C.c_void_p, C.POINTER(C.c_void_p)]),
            'RegisterEventHotKey': (C.c_int32, [C.c_uint32, C.c_uint32, HotKeyID, C.c_void_p, C.c_uint32, C.POINTER(C.c_void_p)]),
            'UnregisterEventHotKey': (C.c_int32, [C.c_void_p]),
            'RemoveEventHandler': (C.c_int32, [C.c_void_p]),
            'GetEventKind': (C.c_uint32, [C.c_void_p]),
            'GetEventParameter': (C.c_int32, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_void_p, C.c_ulong, C.c_void_p, C.c_void_p]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.library, name)
            function.restype, function.argtypes = result, arguments

    def start(self):
        if self.key.value:
            return 0
        target = self.library.GetApplicationEventTarget()
        types = (EventType * 2)(EventType(fourcc('keyb'), 5), EventType(fourcc('keyb'), 6))
        status = self.library.InstallEventHandler(target, self.callback, 2, types, None, C.byref(self.handler))
        if status:
            return status
        # kVK_ANSI_M=46; Carbon cmdKey=1<<8, shiftKey=1<<9.
        status = self.library.RegisterEventHotKey(46, (1 << 8) | (1 << 9), HotKeyID(SIGNATURE, 1),
                                                 target, 0, C.byref(self.key))
        if status:
            self.close()
        return status

    def handle(self, next_handler, event, data):
        identity = HotKeyID()
        status = self.library.GetEventParameter(event, fourcc('----'), fourcc('hkid'), None,
                                               C.sizeof(identity), None, C.byref(identity))
        if status or identity.signature != SIGNATURE or identity.id != 1:
            return -9874  # eventNotHandledErr: preserve other native handlers.
        if self.library.GetEventKind(event) == 6:
            self.down = False
        elif not self.down:
            self.down = True
            self.pressed()
        return 0

    def close(self):
        if self.key.value:
            self.library.UnregisterEventHotKey(self.key)
            self.key = C.c_void_p()
        if self.handler.value:
            self.library.RemoveEventHandler(self.handler)
            self.handler = C.c_void_p()
        self.down = False


class GlobalShortcut(QObject):
    pressed = pyqtSignal(bool)

    def __init__(self, application, tray):
        super().__init__(application)
        self.application, self.tray = application, tray
        self.native = None
        self.active = False
        self.error = ''
        self.pressed.connect(self.activate, Qt.ConnectionType.QueuedConnection)
        application.aboutToQuit.connect(self.close)
        self.set_enabled(application.main_window.global_shortcut_box.isChecked())

    def set_enabled(self, enabled):
        self.error = ''
        if not enabled:
            self.close()
        elif not self.active:
            try:
                self.native = CarbonHotKey(self.native_pressed)
                status = self.native.start()
                if status:
                    self.error = str(status)
                    self.native.close()
                    self.native = None
                else:
                    self.active = True
            except Exception as error:
                self.error = str(error)
                if self.native:
                    self.native.close()
                self.native = None
        self.sync_window()

    def sync_window(self):
        window = self.application.main_window
        window.compact_shortcut.setEnabled(not self.active)
        if self.error:
            window.global_shortcut_box.setText(tr('全局快捷键 ⌘⇧M（未生效）'))
            window.global_shortcut_box.setToolTip(tr('全局快捷键暂不可用，当前仅在控制台窗口内生效。可能已被其他程序占用。'))
        else:
            window.global_shortcut_box.setText(tr('全局快捷键 ⌘⇧M'))
            window.global_shortcut_box.setToolTip(tr('在其他程序中按 ⌘⇧M 呼出控制台；在控制台中按可收起或展开。'))

    def native_pressed(self):
        # Preserve the key's foreground state before requesting app activation.
        # Request activation in the native user event, before queued Qt delivery.
        from AppKit import NSApplication
        app = NSApplication.sharedApplication()
        background = not app.isActive()
        if background:
            if app.respondsToSelector_('activate'):
                app.activate()
            else:
                app.activateIgnoringOtherApps_(True)
        self.pressed.emit(background)

    def activate(self, background=False):
        if not self.active:
            return
        window = self.application.main_window
        if background or not window.isVisible() or window.isMinimized() or not window.isActiveWindow():
            self.tray.show_window()
        elif window.mini:
            window.exit_mini()
        else:
            window.enter_mini()

    def close(self):
        if self.native:
            self.native.close()
            self.native = None
        self.active = False
