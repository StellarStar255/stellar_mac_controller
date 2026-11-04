import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from task_scheduler import TaskStore, tool_specs


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = TaskStore(self.root)

    def create(self, interval=0):
        self.due = time.time() + 10
        return self.store.create('chat', '查看微信', '检查未读消息并报告重点', self.due, interval)

    def test_persistent_one_shot_claim_is_atomic(self):
        task_id = self.create()
        self.assertIsNone(self.store.claim(self.due - 1))
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: TaskStore(self.root).claim(self.due), range(4)))
        self.assertEqual(sum(row is not None for row in claims), 1)
        self.store.finish(task_id, '没有需要关注的内容', now=self.due + 1)
        self.assertIsNone(TaskStore(self.root).claim(self.due + 100))
        self.assertEqual(self.store.list()[0]['status'], 'completed')

    def test_repeat_coalesces_missed_occurrences(self):
        task_id = self.create(1800)
        self.assertIsNotNone(self.store.claim(self.due + 7201))
        self.store.finish(task_id, '检查完成', now=self.due + 7202)
        row = self.store.list()[0]
        self.assertEqual(row['due'], self.due + 9000)
        self.assertIsNone(self.store.claim(self.due + 7203))

    def test_cancel_during_run_survives_completion(self):
        task_id = self.create(60)
        self.store.claim(self.due)
        self.store.update(task_id, 'cancel', 'chat')
        self.store.finish(task_id, '已停止', now=self.due + 1)
        self.assertEqual(self.store.list()[0]['status'], 'cancelled')
        self.assertIsNone(self.store.claim(self.due + 1000))

    def test_pause_resume_and_crash_recovery(self):
        task_id = self.create()
        self.store.update(task_id, 'pause')
        self.assertIsNone(self.store.claim(self.due))
        self.store.update(task_id, 'resume')
        self.store.claim(self.due)
        reopened = TaskStore(self.root)
        reopened.recover()
        self.assertEqual(reopened.list()[0]['status'], 'paused')
        self.assertIsNone(reopened.claim(self.due + 1000))
        reopened.update(task_id, 'resume')
        self.assertIsNotNone(reopened.claim(self.due + 1000))

    def test_invalid_times_and_cross_chat_updates(self):
        for due, interval in [(float('nan'), 0), (time.time() - 1, 0),
                              (time.time() + 10, 1), (time.time() + 10, float('inf'))]:
            with self.assertRaises(ValueError):
                self.store.create('chat', 'test', 'test', due, interval)
        task_id = self.create()
        with self.assertRaises(ValueError):
            self.store.update(task_id, 'cancel', 'other-chat')
        self.assertEqual(self.store.list()[0]['status'], 'pending')

    def test_tools_use_current_folder_and_stable_chat_id(self):
        folder = self.root / 'original chat'
        folder.mkdir()
        (folder / '.chat.json').write_text(json.dumps({'id': 'chat', 'task_config': {'backend': 'test'}}))
        tools = {name: fn for name, fn, _, _ in tool_specs(lambda: str(folder))}
        created = json.loads(tools['schedule_task']('微信检查', '查看微信', delay_seconds=1800))
        folder = folder.rename(self.root / 'renamed chat')
        rows = json.loads(tools['list_scheduled_tasks']())
        self.assertEqual(rows[0]['id'], created['id'])
        self.assertEqual(rows[0]['chat_id'], 'chat')
        with self.assertRaises(ValueError):
            tools['schedule_task']('test', 'test', delay_seconds=1, run_at='2027-01-01T00:00:00')
        tools['update_scheduled_task'](created['id'], 'cancel')
        self.assertEqual(self.store.list()[0]['status'], 'cancelled')

    def test_mcp_subprocess_exposes_and_executes_scheduling_tools(self):
        folder = self.root / 'chat'
        folder.mkdir()
        (folder / '.chat.json').write_text(json.dumps({'id': 'mcp-chat', 'task_config': {'backend': 'test'}}))
        requests = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
                'name': 'schedule_task', 'arguments': {'title': '检查微信', 'prompt': '查看未读消息', 'delay_seconds': 1800}}},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
                'name': 'list_scheduled_tasks', 'arguments': {}}},
        ]
        result = subprocess.run([sys.executable, 'mcp_server.py'],
                                input='\n'.join(json.dumps(r) for r in requests) + '\n',
                                text=True, encoding='utf-8', capture_output=True, timeout=10,
                                env={**os.environ, 'MAC_CTRL_WORKDIR': str(folder)})
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line)['result'] for line in result.stdout.splitlines()]
        self.assertIn('schedule_task', [t['name'] for t in replies[0]['tools']])
        self.assertFalse(replies[1]['isError'], replies[1])
        rows = json.loads(replies[2]['content'][0]['text'])
        self.assertEqual(rows[0]['chat_id'], 'mcp-chat')
        self.assertEqual(rows[0]['interval'], 0)
        self.assertEqual(json.loads(rows[0]['config']), {'backend': 'test'})


if __name__ == '__main__':
    unittest.main()
