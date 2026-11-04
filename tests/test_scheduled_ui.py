"""Exercise scheduling through Qt signals without a live account or desktop actions."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtCore import QCoreApplication, QObject

import chat_store
import scheduled_ui


class FakeBackend:
    def __init__(self, **kwargs):
        self.bridge = kwargs['bridge']
        self.config = kwargs
        self.stopped = False
        self.sent = []

    def load(self, state):
        self.loaded = state

    def state(self):
        return {'session_id': 'scheduled-session'}

    def send(self, *args):
        self.sent.append(args)

    def stop(self):
        self.stopped = True
        self.bridge.done.emit('已停止')

    def shutdown(self):
        pass


class Window(QObject):
    def __init__(self, chat):
        super().__init__()
        self.chat = chat
        self.running = False
        self.backend = None
        self.backend_key = None
        self.updater = Mock(worker=None)
        self.settings = Mock()
        self.visible_entries = []
        self.refresh_history = Mock()
        self.set_status = Mock()

    def set_running(self, value):
        self.running = value

    def add(self, kind, text, save=True):
        self.visible_entries.append((kind, text))


class ScheduledUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root_patch = patch.object(chat_store, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.backend_patch = patch.object(scheduled_ui, 'CodexBackend', FakeBackend)
        self.backend_patch.start()
        self.addCleanup(self.backend_patch.stop)
        self.lock_patch = patch('platform_tools.screen_locked', return_value=False, create=True)
        self.lock_patch.start()
        self.addCleanup(self.lock_patch.stop)
        self.chat = chat_store.Chat()
        self.chat.ensure_folder('测试定时检查微信')
        self.chat.data['task_config'] = {'backend': '本机 Codex', 'model': 'test-model',
                                         'confirm': True, 'confirm_delete': True, 'effort': 'high'}
        self.chat.save()
        self.window = Window(self.chat)
        self.runner = scheduled_ui.ScheduledTasks(self.window)
        self.runner.timer.stop()
        self.addCleanup(self.runner.shutdown)

    def task(self, interval=0):
        due = time.time() + 10
        task_id = self.runner.store.create(self.chat.data['id'], '微信检查', '查看未读消息', due, interval)
        return task_id, due

    def test_routes_results_and_continuation_to_original_chat(self):
        task_id, due = self.task()
        self.runner.start(self.runner.store.claim(due))
        backend = self.runner.backend
        self.assertEqual(backend.config['reasoning_effort'], 'high')
        self.assertTrue(backend.config['confirm_delete'])
        self.assertIn('查看未读消息', backend.sent[0][0])
        self.assertEqual(backend.sent[0][2], str(self.chat.folder))
        backend.bridge.text.emit('需要关注：明天的会议改为十点。')
        backend.bridge.done.emit('完成')
        self.assertFalse(self.window.running)
        self.assertEqual(self.chat.state('本机 Codex'), {'session_id': 'scheduled-session'})
        self.assertIn(('bot', '需要关注：明天的会议改为十点。'), self.window.visible_entries)
        self.assertEqual(self.runner.store.list()[0]['status'], 'completed')
        # Late events from the previous process cannot pollute a new run.
        before = list(self.chat.entries)
        backend.bridge.text.emit('late event')
        self.assertEqual(self.chat.entries, before)

    def test_other_chat_stays_selected_and_is_not_written_to(self):
        other = chat_store.Chat()
        self.window.chat = other
        _, due = self.task()
        self.runner.start(self.runner.store.claim(due))
        self.runner.backend.bridge.text.emit('检查完成')
        self.runner.backend.bridge.done.emit('完成')
        self.assertIs(self.window.chat, other)
        self.assertEqual(other.entries, [])
        self.assertEqual(self.window.visible_entries, [])
        stored = next(c for c in chat_store.list_chats() if c.data['id'] == self.chat.data['id'])
        self.assertIn(['bot', '检查完成'], stored.entries)

    def test_busy_defers_and_cancel_stops_active_task(self):
        task_id, due = self.task(60)
        self.window.running = True
        self.runner.tick()
        self.assertIsNone(self.runner.active)
        self.window.running = False
        self.runner.start(self.runner.store.claim(due))
        backend = self.runner.backend
        self.runner.store.update(task_id, 'cancel')
        self.runner.tick()
        self.assertTrue(backend.stopped)
        self.assertIsNone(self.runner.active)
        self.assertEqual(self.runner.store.list()[0]['status'], 'cancelled')

    def test_second_controller_does_not_recover_live_run(self):
        _, due = self.task()
        self.runner.start(self.runner.store.claim(due))
        second = scheduled_ui.ScheduledTasks(Window(self.chat))
        try:
            self.assertFalse(second.owns_lock)
            self.assertEqual(second.store.list()[0]['status'], 'running')
        finally:
            second.shutdown()

    def test_stop_pauses_repeat_and_failure_records_error(self):
        task_id, due = self.task(60)
        self.runner.start(self.runner.store.claim(due))
        self.runner.backend.stop()
        self.assertEqual(self.runner.store.list()[0]['status'], 'paused')
        self.runner.store.update(task_id, 'resume')
        self.runner.start(self.runner.store.claim(due))
        self.runner.backend.bridge.error.emit('未登录')
        row = self.runner.store.list()[0]
        self.assertEqual(row['status'], 'pending')
        self.assertEqual(row['last_result'], '未登录')

    def test_task_uses_creation_settings_after_chat_settings_change(self):
        due = time.time() + 10
        config = dict(self.chat.data['task_config'], model='creation-model')
        self.runner.store.create(self.chat.data['id'], 'test', 'test', due, config=config)
        self.chat.data['task_config']['model'] = 'later-model'
        self.chat.save()
        self.runner.start(self.runner.store.claim(due))
        self.assertEqual(self.runner.backend.config['model'], 'creation-model')
        self.runner.backend.bridge.done.emit('完成')


if __name__ == '__main__':
    unittest.main()
