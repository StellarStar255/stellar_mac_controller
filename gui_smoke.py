"""Bilingual frozen-window integration checks, enabled only by smoke-test mode."""
import os
from pathlib import Path
import traceback
from PyQt6.QtCore import QTimer
import i18n


def schedule(application):
    def check():
        try:
            window = application.main_window
            assert i18n.language() == 'en'
            assert window.confirm_box.text() == 'Confirm risky actions'
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
            print('Bilingual GUI, stable backend/model keys, drafts and attachments: passed', flush=True)
            QTimer.singleShot(100, application.quit)
        except Exception:
            traceback.print_exc()
            application.exit(1)
    QTimer.singleShot(150, check)
