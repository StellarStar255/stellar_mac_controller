"""Durable desktop tasks shared by the GUI and its MCP subprocesses."""
import json
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class TaskStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / '.scheduled-tasks.sqlite3'
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, title TEXT NOT NULL,
                prompt TEXT NOT NULL, due REAL NOT NULL, interval REAL NOT NULL,
                status TEXT NOT NULL, last_result TEXT NOT NULL DEFAULT '',
                config TEXT NOT NULL DEFAULT '{}')''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, chat_id, title, prompt, due, interval=0, config=None):
        if not title.strip() or not prompt.strip():
            raise ValueError('任务名称和执行内容不能为空')
        if not math.isfinite(due) or due <= time.time():
            raise ValueError('执行时间必须在未来')
        datetime.fromtimestamp(due)  # Validate before committing an unusable timestamp.
        if not math.isfinite(interval) or interval < 0 or 0 < interval < 60:
            raise ValueError('重复间隔至少 60 秒；0 表示只执行一次')
        task_id = uuid.uuid4().hex[:12]
        with self.connect() as db:
            db.execute('INSERT INTO tasks (id,chat_id,title,prompt,due,interval,status,config) VALUES (?,?,?,?,?,?,?,?)',
                       (task_id, chat_id, title.strip(), prompt.strip(), due, interval, 'pending',
                        json.dumps(config or {})))
        return task_id

    def list(self, chat_id=None):
        with self.connect() as db:
            sql = 'SELECT * FROM tasks'
            return [dict(row) for row in db.execute(
                sql + (' WHERE chat_id=?' if chat_id else '') + ' ORDER BY due',
                (chat_id,) if chat_id else ())]

    def update(self, task_id, action, chat_id=None):
        status = {'pause': 'paused', 'resume': 'pending', 'cancel': 'cancelled'}.get(action)
        if not status:
            raise ValueError('action 必须为 pause / resume / cancel')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row or (chat_id and row['chat_id'] != chat_id):
                raise ValueError('找不到本对话的任务')
            if row['status'] in ('completed', 'cancelled', 'failed'):
                raise ValueError('任务已结束，请创建新任务')
            if action == 'resume' and row['status'] != 'paused':
                raise ValueError('只能恢复已暂停的任务')
            db.execute('UPDATE tasks SET status=? WHERE id=?', (status, task_id))

    def claim(self, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM tasks WHERE status='pending' AND due<=? ORDER BY due LIMIT 1",
                             (now,)).fetchone()
            if row:
                db.execute("UPDATE tasks SET status='running' WHERE id=?", (row['id'],))
                return dict(row)

    def finish(self, task_id, result, error=False, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                return
            status, due = row['status'], row['due']
            if status == 'running':
                status = 'failed' if error else 'completed'
                if row['interval']:
                    # Keep cadence while coalescing all missed occurrences into one.
                    due += max(1, math.floor((now - due) / row['interval']) + 1) * row['interval']
                    status = 'pending'
            db.execute('UPDATE tasks SET status=?,due=?,last_result=? WHERE id=?',
                       (status, due, result[-4000:], task_id))

    def recover(self):
        # An interrupted task may have already caused side effects. Require resume.
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='paused',last_result=? WHERE status='running'",
                       ('上次执行被中断；请检查结果后恢复任务。',))


def tool_specs(workdir):
    """Resolve WORKDIR at call time (API changes it between conversations)."""
    def context():
        folder = Path(workdir()).resolve()
        meta = json.loads((folder / '.chat.json').read_text(encoding='utf-8'))
        if not meta.get('task_config'):
            raise ValueError('请先从控制台发送消息，再创建定时任务')
        return TaskStore(folder.parent), meta

    def create(title, prompt, delay_seconds=None, run_at=None, interval_seconds=0):
        if (delay_seconds is None) == (run_at is None):
            raise ValueError('delay_seconds 和 run_at 必须且只能指定一个')
        due = time.time() + float(delay_seconds) if delay_seconds is not None else datetime.fromisoformat(run_at).timestamp()
        store, meta = context()
        task_id = store.create(meta['id'], title, prompt, due, float(interval_seconds), meta['task_config'])
        return json.dumps({'id': task_id, 'next_run': datetime.fromtimestamp(due).astimezone().isoformat(),
                           'interval_seconds': interval_seconds,
                           'note': '程序需保持运行；睡眠或忙碌时延后，恢复后补跑一次。结果写回本对话并尝试桌面通知。'}, ensure_ascii=False)

    def listing():
        store, meta = context()
        rows = store.list(meta['id'])
        for row in rows:
            row['next_run'] = datetime.fromtimestamp(row['due']).astimezone().isoformat()
        return json.dumps(rows, ensure_ascii=False)

    def update(task_id, action):
        store, meta = context()
        store.update(task_id, action, meta['id'])
        return '已更新定时任务：' + task_id + ' ' + action

    def schema(properties, required=()):
        return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}

    return [
        ('schedule_task', create, '创建持久化定时任务，到点由控制台自动调用助手执行。delay_seconds 为几秒后；run_at 为 ISO 日期时间（无时区则按本机时区）。二选一。interval_seconds=0 只执行一次，>=60 周期执行。prompt 只写到点要做的事，不重复调度要求。程序需保持运行。',
         schema({'title': {'type': 'string'}, 'prompt': {'type': 'string'},
                 'delay_seconds': {'type': 'number', 'exclusiveMinimum': 0}, 'run_at': {'type': 'string'},
                 'interval_seconds': {'type': 'number', 'minimum': 0}}, ['title', 'prompt'])),
        ('list_scheduled_tasks', listing, '查看本对话的定时任务、编号、执行时间、状态和上次结果。', schema({})),
        ('update_scheduled_task', update, '暂停、恢复或取消本对话的定时任务。取消或暂停正在执行的任务也会请求停止。',
         schema({'task_id': {'type': 'string'}, 'action': {'type': 'string', 'enum': ['pause', 'resume', 'cancel']}}, ['task_id', 'action'])),
    ]
