"""Bilingual frozen-window integration checks, enabled only by smoke-test mode."""
import os
from pathlib import Path
import traceback
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication
import i18n


def schedule(application):
    def check():
        try:
            window = application.main_window
            assert i18n.language() == 'en'
            assert window.confirm_box.text() == 'Confirm risky actions'
            assert not window.pin_box.isChecked()
            assert not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
            controller = getattr(application, 'global_shortcut', None)
            global_was_active = bool(controller and controller.active)
            if controller:
                assert window.global_shortcut_box.isChecked()
                window.global_shortcut_box.setChecked(False)
                assert not controller.active and window.compact_shortcut.isEnabled()
            if __import__('sys').platform == 'darwin':
                from AppKit import NSApplication, NSApplicationActivationPolicyRegular
                assert NSApplication.sharedApplication().activationPolicy() == NSApplicationActivationPolicyRegular
            backend, model = window.backend_name(), window.model_value()
            draft = 'Unsent draft / 尚未发送'
            attachment = Path(os.environ['MAC_CTRL_DATA_DIR']) / 'language-smoke.txt'
            attachment.parent.mkdir(parents=True, exist_ok=True)
            attachment.write_text('attachment', encoding='utf-8')
            window.input.setPlainText(draft)
            window.composer.add_files([attachment])
            window.language_box.setCurrentIndex(window.language_box.findData('zh_CN'))
            window = application.main_window
            assert window.confirm_box.text() == '危险操作前确认'
            assert window.backend_name() == backend and window.model_value() == model
            assert window.input.toPlainText() == draft and window.composer.files == [attachment]
            assert window.settings.value('language') == 'zh_CN'
            window.language_box.setCurrentIndex(window.language_box.findData('en'))
            window = application.main_window
            assert window.confirm_box.text() == 'Confirm risky actions'
            assert window.backend_name() == backend and window.model_value() == model
            assert window.input.toPlainText() == draft and window.composer.files == [attachment]
            assert window.settings.value('language') == 'en'
            tray = application.desktop_tray
            assert not application.windowIcon().isNull()
            assert not tray.icon.icon().isNull()
            assert tray.menu.actions()[0].text() == 'Open main window'
            if tray.icon.isVisible():
                window.close()
                assert not window.isVisible()
                tray.show_window()
                assert window.isVisible()
                assert window.input.toPlainText() == draft
            tray.show_settings()
            assert window.gear_btn.isChecked()
            window.activateWindow()
            QApplication.setActiveWindow(window)
            window.input.setFocus()
            application.processEvents()
            for expected in (True, False):
                target = application.focusWidget() or window
                for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                    QApplication.sendEvent(target, QKeyEvent(kind, Qt.Key.Key_M,
                        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, 'M'))
                assert window.mini is expected, 'Compact-view shortcut failed'
            window.language_box.setCurrentIndex(window.language_box.findData('zh_CN'))
            assert tray.menu.actions()[0].text() == '打开主窗口'
            window = application.main_window
            window.language_box.setCurrentIndex(window.language_box.findData('en'))
            if controller:
                window = application.main_window
                window.global_shortcut_box.setChecked(True)
                if global_was_active:
                    assert controller.active and not window.compact_shortcut.isEnabled()
            print('Bilingual GUI, stable backend/model keys, drafts and attachments: passed', flush=True)
            print('Application icon, tray menu, window restore and translated tray actions: passed', flush=True)
            print('Regular Dock application and compact-view shortcut: passed', flush=True)
            print('Window stays-on-top disabled; Control/Command-Shift-M toggle: passed', flush=True)
            print('Global shortcut preference, language rebuild and local fallback: passed', flush=True)
            QTimer.singleShot(100, application.quit)
        except Exception:
            traceback.print_exc()
            application.exit(1)
    QTimer.singleShot(150, check)
