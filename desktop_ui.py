"""Application-owned tray menu; actions always target the current language window."""
import sys
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon
from i18n import tr

ASSETS = Path(__file__).resolve().parent / 'assets'


class DesktopTray:
    def __init__(self, application):
        self.application = application
        icon = QIcon(str(ASSETS / ('tray.svg' if sys.platform == 'darwin' else 'app-icon.png')))
        if sys.platform == 'darwin':
            icon.setIsMask(True)
        self.icon = QSystemTrayIcon(icon, application)
        self.menu = QMenu()
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self.activate)
        application.applicationStateChanged.connect(self.application_activated)
        self.refresh()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.icon.show()
            application.setQuitOnLastWindowClosed(False)

    def application_activated(self, state):
        if (state == Qt.ApplicationState.ApplicationActive
                and not self.application.main_window.isVisible()):
            self.show_window()

    def refresh(self):
        self.icon.setToolTip(tr('Mac 控制台'))
        self.menu.clear()
        self.menu.addAction(tr('打开主窗口'), self.show_window)
        self.menu.addAction(tr('设置'), self.show_settings)
        self.menu.addSeparator()
        self.menu.addAction(tr('退出程序'), self.quit)

    def activate(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self):
        window = self.application.main_window
        window.exit_mini()
        window.showNormal()
        window.raise_()
        if sys.platform == 'darwin':
            from AppKit import NSApplication
            native = NSApplication.sharedApplication()
            if native.respondsToSelector_('activate'):
                native.activate()
            else:
                native.activateIgnoringOtherApps_(True)
        window.activateWindow()

    def show_settings(self):
        self.show_window()
        self.application.main_window.gear_btn.setChecked(True)

    def quit(self):
        self.application.main_window.request_quit()

    def cleanup(self):
        window = self.application.main_window
        window.save_state()
        if window.backend:
            window.backend.shutdown()
        self.icon.hide()
