"""Serial task execution using the same backends, permissions and chat history."""
import json
import os
import sys

from PyQt6.QtCore import QObject, QTimer, QLockFile
from PyQt6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QListWidget,
                             QPushButton, QVBoxLayout, QMessageBox)

import chat_store
from backends import ApiBackend, Bridge, ClaudeCodeBackend, CodexBackend
from i18n import tr
from task_scheduler import TaskStore


class ScheduledTasks(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.store = TaskStore(chat_store.ROOT)
        self.active = None
        self.backend = None
        # Only one GUI process may operate the desktop for scheduled tasks.
        self.lock = QLockFile(str(chat_store.ROOT / '.scheduler.lock'))
        self.lock.setStaleLockTime(0)
        self.owns_lock = self.lock.tryLock(0)
        if self.owns_lock:
            self.store.recover()
        self.timer = QTimer(self, interval=2000, timeout=self.tick)
        if self.owns_lock:
            self.timer.start()
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def tick(self):
        if not self.owns_lock:
            return
        try:
            if self.active:
                row = next((r for r in self.store.list() if r['id'] == self.active['id']), None)
                if row and row['status'] in ('paused', 'cancelled'):
                    self.backend.stop()
                return
            if self.window.running or (self.window.updater.worker and self.window.updater.worker.isRunning()):
                return
            if sys.platform == 'darwin':
                import platform_tools
                if platform_tools.screen_locked():
                    return
            task = self.store.claim()
            if task:
                self.start(task)
        except Exception as exc:
            if self.active:
                self.finish(str(exc), error=True)
            else:
                self.window.set_status(tr('定时任务出错') + ': ' + str(exc))

    def start(self, task):
        self.active = task
        self.texts = []
        self.chat = None
        self.chat = next((c for c in chat_store.list_chats() if c.data['id'] == task['chat_id']), None)
        if not self.chat:
            self.finish(tr('定时任务的对话已删除'), error=True)
            return
        if self.window.chat.data['id'] == task['chat_id']:
            self.chat = self.window.chat
        config = json.loads(task['config']) or self.chat.data['task_config']
        self.config = config
        name = config['backend']
        bridge = Bridge()
        self.bridge = bridge
        # Each run owns a bridge. Ignore any late signals after stopping it.
        def guard(fn):
            return lambda *args: fn(*args) if self.active and self.bridge is bridge else None
        bridge.text.connect(guard(self.on_text))
        bridge.tool.connect(guard(lambda n, a: self.add('tool', f'{n} {a}')))
        bridge.tool_result.connect(guard(lambda error, s: self.add('err', s) if error else None))
        bridge.done.connect(guard(self.finish))
        bridge.error.connect(guard(lambda s: self.finish(s, error=True)))
        kwargs = dict(bridge=bridge, model=config['model'], confirm=config['confirm'],
                      self_pid=os.getpid(), confirm_delete=config['confirm_delete'])
        if name == '本机 Codex':
            self.backend = CodexBackend(**kwargs, reasoning_effort=config.get('effort', ''))
        elif name == '本机 Claude Code':
            self.backend = ClaudeCodeBackend(**kwargs)
        elif name == 'Claude API':
            self.backend = ApiBackend(**kwargs, api_key=self.window.settings.value('api_key', ''))
        else:
            raise ValueError('Unknown task backend: ' + name)
        self.backend.load(self.chat.state(name))
        self.window.set_running(True)
        self.add('meta', tr('定时任务开始') + ': ' + task['title'])
        prompt = ('[定时任务自动触发；请执行本次任务，不要重新创建或修改定时任务。'
                  '结果会写回此对话并尝试桌面通知。]\n' + task['prompt'])
        self.backend.send(prompt, None, str(self.chat.folder))

    def add(self, kind, text):
        if not self.chat:
            return
        self.chat.add(kind, text)
        if self.window.chat.data['id'] == self.chat.data['id']:
            self.window.add(kind, text, save=False)

    def on_text(self, text):
        self.texts.append(text)
        self.add('bot', text)

    def finish(self, info, error=False):
        if not self.active:
            return
        task = self.active
        stopped = info == '已停止'
        if stopped:
            # The Stop button pauses repeating tasks as well.
            row = next(r for r in self.store.list() if r['id'] == task['id'])
            if row['status'] == 'running':
                self.store.update(task['id'], 'pause')
        result = '\n'.join(getattr(self, 'texts', []))
        if error or stopped or not result:
            result = info + ('\n' + result if result else '')
        if self.backend and self.chat:
            self.chat.set_state(self.config['backend'], self.backend.state())
            self.chat.save()
            # The ordinary idle backend still has its old conversation state.
            if self.window.chat.data['id'] == self.chat.data['id']:
                if self.window.backend:
                    self.window.backend.shutdown()
                self.window.backend = None
                self.window.backend_key = None
        self.add('meta_err' if error else 'meta', tr('定时任务结束') + ': ' + info)
        self.store.finish(task['id'], result, error=error)
        self.active = None
        backend, self.backend = self.backend, None
        if backend:
            backend.shutdown()
        self.window.set_running(False)
        self.window.refresh_history()
        tray = getattr(QApplication.instance(), 'desktop_tray', None)
        if tray:
            tray.icon.showMessage(tr('定时任务结束') + ': ' + task['title'], result[:500])

    def shutdown(self):
        self.timer.stop()
        if self.backend:
            # Leave running in the database: next launch pauses interrupted tasks.
            self.active = None
            self.backend.shutdown()
        if self.owns_lock:
            self.lock.unlock()
            self.owns_lock = False

    def show_manager(self):
        dialog = QDialog(self.window)
        dialog.setWindowTitle(tr('定时任务'))
        dialog.resize(760, 380)
        theme = self.window.theme
        dialog.setStyleSheet(
            f"QDialog {{ background: {theme['bg']}; color: {theme['text']}; }}"
            f"QLabel {{ color: {theme['text']}; }}"
            f"QListWidget {{ background: {theme['surface']}; color: {theme['text']}; "
            f"border: 1px solid {theme['border']}; border-radius: 6px; }}"
            f"QListWidget::item:selected {{ background: {theme['accent']}; color: {theme['accent_text']}; }}")
        layout = QVBoxLayout(dialog)
        help_label = QLabel(tr('程序需保持运行；睡眠或忙碌时延后，恢复后补跑一次。'))
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        listing = QListWidget()
        layout.addWidget(listing)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        rows = []

        def refresh():
            import datetime
            selected = listing.currentRow()
            rows[:] = self.store.list()
            listing.clear()
            for row in rows:
                due = datetime.datetime.fromtimestamp(row['due']).strftime('%Y-%m-%d %H:%M:%S')
                repeat = f" / {row['interval']:g}s" if row['interval'] else ''
                status = tr({'pending': '待执行', 'running': '执行中', 'paused': '已暂停',
                             'cancelled': '已取消', 'completed': '已完成', 'failed': '失败'}[row['status']])
                listing.addItem(f"{status} | {due}{repeat} | {row['title']} | {row['id']}")
                listing.item(listing.count() - 1).setToolTip(row['prompt'] + '\n\n' + row['last_result'])
            if rows:
                listing.setCurrentRow(max(0, min(selected, len(rows) - 1)))

        def act(action):
            index = listing.currentRow()
            if index < 0:
                return
            try:
                self.store.update(rows[index]['id'], action)
                self.tick()
            except ValueError as exc:
                QMessageBox.information(dialog, tr('定时任务'), str(exc))
            refresh()

        for label, action in [('暂停任务', 'pause'), ('恢复任务', 'resume'), ('取消任务', 'cancel')]:
            button = QPushButton(tr(label))
            button.clicked.connect(lambda checked=False, a=action: act(a))
            buttons.addWidget(button)
        button = QPushButton(tr('刷新'))
        button.clicked.connect(refresh)
        buttons.addWidget(button)
        refresh()
        dialog.exec()
