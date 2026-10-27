"""对话存档：每个对话一个文件夹，放在 ~/Documents/Mac 控制台/ 下。

  <日期 时间 标题>/
      .chat.json      对话记录 + 后端的续聊状态（Claude Code 会话 id / API 消息）
      *.md            模型写的笔记（note_write）
      其它文件         run_shell 的工作目录也在这里，下载、生成的文件默认放这

删掉文件夹就等于删掉这个对话。
导入以前的 Claude Code 会话：python3 chat_store.py import <session_id>
"""
import calendar
import glob
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(os.environ["MAC_CTRL_DATA_DIR"]) if os.environ.get("MAC_CTRL_DATA_DIR") else Path.home() / "Documents" / "Mac 控制台"
META = ".chat.json"
_CONTEXT_PREFIX = re.compile(r"^\[当前时间[^\]]*\]\n?")
_SKIP_USER = {"Continue from where you left off."}
TRANSCRIPT = "对话记录.md"


def _good_title(text):
    """像样的标题：至少 8 个字，别是“你好/继续”这种。"""
    return len(text.strip()) >= 8


def _safe(name, n=24):
    name = re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ", name).strip()
    return (name[:n].strip() or "新对话")


class Chat:
    def __init__(self, data=None, folder=None):
        self.data = data or {"id": uuid.uuid4().hex[:12], "title": "", "created": time.time(),
                             "updated": time.time(), "entries": [], "state": {}}
        self.folder = Path(folder) if folder else None

    # ---- 基本属性
    @property
    def title(self):
        return self.data.get("title") or "新对话"

    @property
    def entries(self):
        return self.data["entries"]

    def state(self, backend):
        return self.data["state"].get(backend, {})

    def set_state(self, backend, st):
        self.data["state"][backend] = st

    def ensure_folder(self, first_text=""):
        """第一次发消息时才建文件夹，用第一句话当标题。"""
        if self.folder is None:
            if not self.data["title"]:
                self.data["title"] = _safe(first_text, 30)
            stamp = time.strftime("%Y-%m-%d %H%M", time.localtime(self.data["created"]))
            folder = ROOT / f"{stamp} {_safe(self.data['title'])}"
            i = 2
            while folder.exists():
                folder = ROOT / f"{stamp} {_safe(self.data['title'])} ({i})"
                i += 1
            folder.mkdir(parents=True)
            self.folder = folder
        return self.folder

    def maybe_retitle(self, text):
        """第一句太短（如“你好”）时，用第一句像样的话当标题，并同步改文件夹名。"""
        if _good_title(self.title) or not _good_title(text):
            return
        self.data["title"] = _safe(text, 30)
        if self.folder is not None:
            new = self.folder.with_name(f"{self.folder.name[:15]} {_safe(self.data['title'])}")
            if not new.exists():
                try:
                    self.folder = self.folder.rename(new)
                except OSError:
                    pass

    def add(self, kind, text):
        self.entries.append([kind, text])
        self.save()

    def save(self):
        if self.folder is None:
            return
        self.data["updated"] = time.time()
        tmp = self.folder / (META + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.folder / META)
        self._write_transcript()

    def _write_transcript(self):
        """给人看的对话记录（只含你说的和它答的），在访达里直接就能读调研结果。"""
        lines = [f"# {self.title}\n"]
        prev = None
        for kind, text in self.entries:
            if kind == "user":
                sep = "" if prev == "files" else "\n---\n"      # 附件和紧跟的那句话算同一条
                lines.append(f"{sep}\n**我：** {text}\n")
            elif kind == "bot":
                lines.append(f"\n{text}\n")
            elif kind == "files":
                names = "、".join(f"[{Path(f).name}](<{f}>)" for f in json.loads(text))
                lines.append(f"\n---\n\n**我附上了：** {names}\n")
            prev = kind
        (self.folder / TRANSCRIPT).write_text("".join(lines), encoding="utf-8")

    def notes(self):
        if not self.folder:
            return []
        return sorted(p for p in self.folder.iterdir()
                      if p.is_file() and not p.name.startswith(".") and p.name != TRANSCRIPT)


def list_chats():
    chats = []
    for meta in ROOT.glob(f"*/{META}"):
        try:
            chats.append(Chat(json.loads(meta.read_text(encoding="utf-8")), meta.parent))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(chats, key=lambda c: c.data.get("updated", 0), reverse=True)


# ---------------------------------------------------------------- 导入以前的 Claude Code 会话

def import_claude_session(session_id):
    files = glob.glob(str(Path.home() / ".claude" / "projects" / "*" / f"{session_id}*.jsonl"))
    if not files:
        raise SystemExit(f"找不到会话 {session_id}")
    path = files[0]
    sid = Path(path).stem
    entries, first_ts, tool_names = [], None, {}
    for line in open(path, encoding="utf-8"):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if first_ts is None and ev.get("timestamp"):
            first_ts = ev["timestamp"]
        msg = ev.get("message") or {}
        content = msg.get("content")
        if ev.get("type") == "user":
            if isinstance(content, str):
                if content.strip() not in _SKIP_USER:
                    entries.append(["user", _CONTEXT_PREFIX.sub("", content)])
            elif isinstance(content, list):
                for b in content:
                    if b.get("type") == "text" and b["text"].strip() not in _SKIP_USER:
                        entries.append(["user", _CONTEXT_PREFIX.sub("", b["text"])])
                    elif b.get("type") == "tool_result" and b.get("is_error"):
                        c = b.get("content")
                        c = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [])
                        entries.append(["err", c[:200]])
        elif ev.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if b.get("type") == "text" and b.get("text", "").strip():
                    entries.append(["bot", b["text"]])
                elif b.get("type") == "tool_use":
                    args = json.dumps(b.get("input"), ensure_ascii=False)
                    entries.append(["tool", f"{b['name'].removeprefix('mcp__mac__')} "
                                            f"{args if len(args) <= 160 else args[:160] + '…'}"])
    users = [t for k, t in entries if k == "user"]
    first_user = next((t for t in users if _good_title(t)), users[0] if users else "导入的对话")
    created = calendar.timegm(time.strptime(first_ts[:19], "%Y-%m-%dT%H:%M:%S")) if first_ts else time.time()
    chat = Chat()
    chat.data.update(title=_safe(first_user, 30), created=created, entries=entries)
    chat.data["entries"].append(["meta", "（从之前的 Claude Code 会话导入，可以直接接着说）"])
    chat.set_state("本机 Claude Code", {"session_id": sid})
    chat.ensure_folder()
    chat.save()
    return chat


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "import":
        for s in sys.argv[2:]:
            c = import_claude_session(s)
            print(f"已导入：{c.folder}（{len(c.entries)} 条记录）")
    else:
        for c in list_chats():
            print(time.strftime("%m-%d %H:%M", time.localtime(c.data["updated"])), c.title, "→", c.folder)
