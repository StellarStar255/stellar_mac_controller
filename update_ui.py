"""Non-blocking update check, download and installer handoff."""
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox
import updater
from i18n import tr


class Worker(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.result.emit(self.action())
        except Exception as error:
            self.failed.emit(str(error))


class UpdateController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.button = None
        self.worker = None

    def _work(self, action, callback):
        self.button.setEnabled(False)
        worker = Worker(action, self)
        self.worker = worker
        worker.result.connect(callback)
        worker.failed.connect(self._error)
        def finished():
            if self.worker is worker:
                self.worker = None
            worker.deleteLater()
        worker.finished.connect(finished)
        worker.start()

    def _error(self, message):
        self.button.setEnabled(True)
        self.button.setText(tr("重试检查更新"))
        QMessageBox.warning(self.window, tr("更新失败"), tr(message + "\n当前版本仍可继续使用。"))

    def check(self):
        if self.window.running:
            QMessageBox.information(self.window, tr("更新"), tr("请先等待任务完成或停止任务，再更新。"))
            return
        self.button.setText(tr("正在检查更新…"))
        self._work(updater.check_update, self._checked)

    def _checked(self, entry):
        self.button.setEnabled(True)
        self.button.setText(tr("检查更新"))
        if not entry:
            QMessageBox.information(self.window, tr("更新"), tr("当前已是最新版本。"))
            return
        if QMessageBox.question(self.window, tr("发现新版本"), tr(f"发现 v{entry['version']}。立即下载安装？\n安装时程序会退出，对话和设置会保留。")) != QMessageBox.StandardButton.Yes:
            return
        self.button.setText(tr("正在下载安装包…"))
        self._work(lambda: updater.download_update(entry), self._downloaded)

    def _downloaded(self, path):
        if self.window.running:
            self._error("下载期间启动了新任务。请完成任务后再更新。")
            return
        try:
            self.window.save_state()
            updater.launch_installer(path)
            QTimer.singleShot(200, self.window.request_quit)
        except Exception as error:
            self._error(str(error))
