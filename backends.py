"""三种“大脑”：
- ClaudeCodeBackend：调用本机已登录的 Claude Code（claude -p），不需要 API Key；工具通过 mcp_server.py 提供。
- ApiBackend：直接调用 Claude API（需要 ANTHROPIC_API_KEY），工具在本进程内执行。
- CodexBackend：调用已登录的 Codex CLI，使用相同的 Mac MCP 工具。

都在后台线程运行，通过 Bridge 的 Qt 信号把进度推给界面。
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from runtime_support import external_env

from PyQt6.QtCore import QObject, pyqtSignal

HERE = Path(__file__).resolve().parent
CLAUDE = shutil.which("claude") or "/opt/homebrew/bin/claude"
CODEX = shutil.which("codex") or "/opt/homebrew/bin/codex"
MAX_STEPS = 60


def mcp_command():
    return (sys.executable, ["--mcp"] if getattr(sys, "frozen", False)
            else [str(HERE / "mcp_server.py")])


def cli_prefix(executable, package, entry):
    if sys.platform == "win32" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        # Invoke Node directly; passing JSON prompts through cmd.exe is unsafe.
        script = Path(executable).parent / "node_modules" / package / entry
        node = shutil.which("node")
        if not node or not script.is_file():
            raise RuntimeError("请安装原生 CLI，或确认 Node.js 与 npm 全局 CLI 的安装完整。")
        return [node, str(script)]
    return [executable]


def terminate_process(proc, force=False):
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, timeout=10)
    else:
        os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)


def codex_model_catalog():
    """本机 CLI 的模型及推理档位目录；缓存不可用时保留默认和手动模型。"""
    cache = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "models_cache.json"
    try:
        models = json.loads(cache.read_text()).get("models", [])
        return {m["slug"]: m for m in models if isinstance(m, dict)
                and m.get("visibility") == "list" and isinstance(m.get("slug"), str)}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def codex_models():
    return list(codex_model_catalog())


def codex_external_tool_overrides(workdir=""):
    """只对控制台的子进程禁用外部工具，保留账号、模型等用户配置。"""
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    root = Path(workdir or Path.home()).resolve()
    paths = [home / "config.toml"] + [p / ".codex" / "config.toml" for p in (root, *root.parents)]
    overrides = {"features.plugins": False, "features.computer_use": False,
                 "mcp_servers": {}, "plugins": {}}

    def collect(config):
        for server in config.get("mcp_servers", {}):
            if server != "mac":
                overrides["mcp_servers"][server] = {"enabled": False}
        for plugin in config.get("plugins", {}):
            overrides["plugins"][plugin] = {"enabled": False}
        for profile in config.get("profiles", {}).values():
            if isinstance(profile, dict):
                collect(profile)

    for path in paths:
        try:
            collect(tomllib.loads(path.read_text()))
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"无法读取工具配置 {path}：{exc}") from exc
    return overrides


def codex_reasoning_levels(model):
    info = codex_model_catalog().get(model)
    if info is None:
        # 自定义模型/CLI 默认模型无目录记录时只提供常用档位，由 CLI 验证。
        return ["low", "medium", "high"]
    return list(dict.fromkeys(level["effort"] for level in info.get("supported_reasoning_levels", [])
                             if isinstance(level, dict) and isinstance(level.get("effort"), str)))


SYSTEM_PROMPT = """你是运行在用户 Mac 上的操作助手，通过工具直接使用这台电脑上的程序来完成用户的请求。

做事方法（按优先级，能用前面的就别用后面的）：
1. 能用 AppleScript / 终端命令直接完成的（访达、音乐、备忘录、提醒事项、日历、邮件、系统设置项、文件操作、下载等），优先用 run_applescript / run_shell / open，最快最稳。
2. 浏览器里的事（搜索、看网页、翻页、点链接、填表、收集资料、找图片地址）：一律先用 web_read 读网页（正文 + 带编号的元素清单），再用 web_act 按编号点击 / 填写 / 提交 / 滚动 / 打开网址；批量提取数据可以用 web_act 的 js。不需要截图，也不要用 click 按坐标点网页。
3. 其它程序的界面：先 activate_app 把它切到前面，再 read_ui 读取带编号的界面元素，用 ui_action 按编号操作（press 优先）。菜单命令可以 read_ui(include_menu_bar=true) 后直接 press 菜单项。
4. 只有前面都不行时（微信这类自绘界面、游戏、需要看图片本身的内容、判断页面长什么样），才用 screenshot 看屏幕，再用 click / type_text / press_key / scroll 按坐标操作。截图很慢也很贵，能读文字就别截图。
5. 每做完关键一步都要确认结果（重新 web_read / read_ui，必要时才截图），不要假设成功。页面或界面变化后旧编号会失效。

用户附带的文件：
- 消息末尾会列出用户附带的图片、PDF 等文件。能直接看的就直接看（本机模式用 Read 工具，图片和 PDF 都能读）；Word / Excel / PPT 等可以用 run_shell 转换（如 textutil -convert txt、python）后再读。

工作文件夹与笔记（重要）：
- 每个对话有自己的工作文件夹（消息开头会告诉你路径），run_shell 的当前目录就是它。下载、生成的文件默认放这里，除非用户指定了别的位置。
- 调研、收集资料、比较、整理信息这类任务：边做边用 note_write 把要点、数据、来源链接追加到「调研笔记」，不要只留在对话里；做完后用 note_write(append=false) 整理一份「总结」。这样即使程序关闭，下次也能接着做。
- 用户说“继续”或回到之前的话题时，先 note_list / note_read 看看已有的笔记和文件，接着往下做，不要从头重来。

注意：
- 「Mac 控制台」是你自己的控制界面：执行任务时它会缩成屏幕右下角的小条，截图和点击时还会自动临时隐藏，不会挡住页面，不用理会也不要操作它。
- type_text / press_key 会发给最前面的程序，输入前先确认焦点在正确的程序和输入框里。
- 输入文字和按回车是分开的两步；发送消息、付款、提交表单等不可撤销的操作，先用一句话向用户确认，除非用户已经明确要求直接做。
- 用户要求删除文件时按要求执行，不要重复征求同意；工具会按照用户的确认设置处理。删除范围不明确时先问清具体文件。
- 不要向密码框输入内容，需要密码时请用户自己输入。
- 连续失败两次就换一种方法；实在做不到就说明原因。
- 权限或授权被拒绝时立即停止访问该应用，不得换工具绕过。报错包含“Computer Use was not approved to use”时，表示 Computer Use 未获目标应用的访问授权；不能据此说成 macOS 系统权限缺失或用户未登录。说明目标应用及原始报错，并请用户在桌面客户端的 Computer Use 设置中检查应用授权，再重试。
- 用简体中文简洁地回答，完成后用一两句话说明做了什么、结果如何。"""

if sys.platform != "darwin":
    SYSTEM_PROMPT = (SYSTEM_PROMPT.replace("Mac", "电脑") +
                     "\n当前系统是 " + sys.platform +
                     "。只使用工具列表中提供的工具，不使用 AppleScript、Quartz 或 macOS 命令。"
                     "Windows 优先 read_ui/ui_action；Linux X11 使用截图和坐标。"
                     "浏览器使用截图/鼠标/键盘，当前平台不提供 web_read/web_act。"
                     "Windows run_shell 使用 cmd.exe 语法，复杂脚本请显式调用 powershell；Linux 使用 POSIX shell。")


class Bridge(QObject):
    text = pyqtSignal(str)                 # 模型说的话
    tool = pyqtSignal(str, str)            # 工具名, 参数摘要
    tool_result = pyqtSignal(bool, str)    # 是否出错, 结果摘要
    done = pyqtSignal(str)                 # 结束信息
    error = pyqtSignal(str)
    model = pyqtSignal(str)                # 实际使用的模型 id（如 claude-opus-5-5）
    reasoning = pyqtSignal(str)            # 本轮推理档位（应用选择）
    busy = pyqtSignal()                    # 空闲后又开始干活（处理排队的消息）


IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
             ".webp": "image/webp"}
TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".py", ".js", ".ts", ".html", ".css", ".xml", ".yaml", ".yml",
            ".log", ".sh", ".sql", ".ini", ".toml"}


def files_note(files, how):
    if not files:
        return ""
    lines = "\n".join(f"- {f}" for f in files)
    return f"\n\n[用户附带了 {len(files)} 个文件（{how}）：\n{lines}]"


def summarize_args(args):
    if not args:
        return ""
    s = json.dumps(args, ensure_ascii=False)
    return s if len(s) <= 160 else s[:160] + "…"


def context_note(front_app, workdir=None):
    note = f"[当前时间 {time.strftime('%Y-%m-%d %H:%M')}"
    if front_app:
        note += f"；用户发消息前正在使用的程序：{front_app}"
    if workdir:
        note += f"；本对话的工作文件夹：{workdir}"
    return note + "]\n"


# ---------------------------------------------------------------- 本机 Claude Code

class ClaudeCodeBackend:
    """一个对话对应一个常驻的 claude 进程（stream-json 输入）：执行中也能继续发消息，
    Claude 会在当前步骤结束后看到；后续消息也省掉了每次启动的时间。"""
    name = "本机 Claude Code"

    def __init__(self, bridge, model="", confirm=True, self_pid=0, confirm_delete=False):
        self.bridge, self.model, self.confirm, self.self_pid = bridge, model, confirm, self_pid
        self.confirm_delete = confirm_delete
        self.session_id = None
        self.workdir = ""
        self.proc = None
        self.busy = False
        self._stopped = False
        self._lock = threading.Lock()
        self._last = {"cost": 0.0, "turns": 0}     # result 里的花费/轮数是整个进程累计的，用来算每轮的增量

    def state(self):
        return {"session_id": self.session_id} if self.session_id else {}

    def load(self, state):
        self.session_id = (state or {}).get("session_id")

    def _kill(self):
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            try:   # 连同 MCP 服务和它正在跑的命令（curl 等）整组结束，避免留下孤儿进程
                terminate_process(proc)
            except ProcessLookupError:
                pass

    def stop(self):
        self._stopped = True
        self._kill()

    def shutdown(self):
        """换对话 / 关窗口时结束常驻进程（不算“停止”，不发任何消息）。"""
        self._stopped = True
        self.busy = False
        self._kill()

    def send(self, text, front_app=None, workdir="", files=()):
        prompt = context_note(front_app, workdir) + text + files_note(files, "请用 Read 工具直接查看")
        with self._lock:
            if self.proc is None or self.proc.poll() is not None or workdir != self.workdir:
                self._kill()
                self.workdir = workdir
                if not self._start():
                    return
            self._stopped = False
            self.busy = True
            msg = {"type": "user", "message": {"role": "user", "content": prompt}}
            try:
                self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self.busy = False
                self.bridge.error.emit(f"发送给 Claude Code 失败：{e}")

    def _mcp_config(self):
        executable, args = mcp_command()
        return json.dumps({"mcpServers": {"mac": {
            "command": executable, "args": args,
            "env": {"MAC_CTRL_SELF_PID": str(self.self_pid), "MAC_CTRL_CONFIRM": "1" if self.confirm else "0",
                    "MAC_CTRL_CONFIRM_DELETE": "1" if self.confirm_delete else "0",
                    "MAC_CTRL_WORKDIR": self.workdir, "PYTHONPATH": str(HERE)}}}})

    def _start(self):
        cmd = cli_prefix(CLAUDE, "@anthropic-ai/claude-code", "cli.js") + ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--mcp-config", self._mcp_config(), "--strict-mcp-config",
               "--tools", "Read", "--allowedTools", "mcp__mac", "Read",
               "--append-system-prompt", SYSTEM_PROMPT]
        if self.workdir:
            cmd += ["--add-dir", self.workdir]
        if self.model:
            cmd += ["--model", self.model]
        if self.session_id:
            cmd += ["--resume", self.session_id]
        env = {k: v for k, v in external_env().items() if k != "ANTHROPIC_API_KEY"}   # 走 Claude Code 的登录账号
        try:
            self.proc = subprocess.Popen(cmd, cwd=str(Path.home()), env=env, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
                                         start_new_session=True)
        except FileNotFoundError:
            self.bridge.error.emit(f"找不到 claude 命令（{CLAUDE}），请先安装并登录 Claude Code。")
            return False
        self._last = {"cost": 0.0, "turns": 0}
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        return True

    def _read(self, proc):
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("session_id"):
                self.session_id = ev["session_id"]
            if proc is self.proc and not self._stopped:
                self._handle(ev)
        proc.wait()
        if proc is not self.proc and not self._stopped:
            return                                   # 已被新进程替换（换了工作文件夹等），安静退出
        if self._stopped:
            if self.busy:
                self.busy = False
                self.bridge.done.emit("已停止")
            return
        err = (proc.stderr.read() or "").strip()
        self.proc = None
        if self.busy:
            self.busy = False
            if self.session_id and "No conversation found" in err:
                self.session_id = None
                err = "找不到之前的会话记录（可能已被 Claude Code 清理），已改为新会话，请再发一次。"
            self.bridge.error.emit(f"Claude Code 异常退出（{proc.returncode}）：{err[-800:]}")

    def _handle(self, ev):
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init" and ev.get("model"):
            self.bridge.model.emit(ev["model"])
        if t in ("assistant", "user") and not self.busy:
            self.busy = True                         # 排队的消息开始处理了
            self.bridge.busy.emit()
        if t == "assistant":
            for b in ev.get("message", {}).get("content", []):
                if b.get("type") == "text" and b.get("text", "").strip():
                    self.bridge.text.emit(b["text"])
                elif b.get("type") == "tool_use":
                    name = b["name"].removeprefix("mcp__mac__")
                    self.bridge.tool.emit("read_file" if name == "Read" else name, summarize_args(b.get("input")))
        elif t == "user":
            content = ev.get("message", {}).get("content", [])
            for b in content if isinstance(content, list) else []:
                if b.get("type") == "tool_result":
                    self.bridge.tool_result.emit(bool(b.get("is_error")), _result_text(b.get("content")))
        elif t == "result":
            self.busy = False
            cost = (ev.get("total_cost_usd") or 0) - self._last["cost"]
            turns = (ev.get("num_turns") or 0) - self._last["turns"]
            self._last = {"cost": ev.get("total_cost_usd") or 0, "turns": ev.get("num_turns") or 0}
            if ev.get("is_error") or ev.get("subtype") != "success":
                self.bridge.error.emit(str(ev.get("result") or ev.get("subtype") or "未知错误"))
                return
            secs = (ev.get("duration_ms") or 0) / 1000
            self.bridge.done.emit(f"完成 · {max(turns, 1)} 轮 · {secs:.0f} 秒" + (f" · ${cost:.3f}" if cost > 0 else ""))


def _result_text(content):
    if isinstance(content, str):
        s = content
    else:
        s = " ".join(c.get("text", "[图片]") if c.get("type") == "text" else "[截图]" for c in content or [])
    s = s.strip().replace("\n", " ⏎ ")
    return s if len(s) <= 200 else s[:200] + "…"


# ---------------------------------------------------------------- 本机 Codex

class CodexBackend(ClaudeCodeBackend):
    """exec JSONL 每轮启动、按 thread_id 续聊；运行中收到的消息按顺序排队。"""
    name = "本机 Codex"

    def __init__(self, bridge, model="", confirm=True, self_pid=0, confirm_delete=False, reasoning_effort=""):
        super().__init__(bridge, model, confirm, self_pid, confirm_delete)
        self.pending = []
        self._silent = False
        self._access_denial = None
        # 兼容旧版已保存的规则自动模式，回到 CLI 默认，绝不发送无效的 auto。
        self.reasoning_effort = "" if reasoning_effort == "auto" else reasoning_effort

    def send(self, text, front_app=None, workdir="", files=()):
        prompt = context_note(front_app, workdir) + text + files_note(files, "请用 mac 的 run_shell 查看；图片已直接附带")
        with self._lock:
            self.pending.append((prompt, workdir, tuple(files)))
            if self.busy:
                return
            self._stopped = False
            self._silent = False
            self.busy = True
            threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        with self._lock:
            self._stopped = True
            self.pending.clear()
            self._kill()

    def shutdown(self):
        self._silent = True
        self.stop()

    def _command(self, files):
        executable, args = mcp_command()
        # 原生命令工具关闭：Mac 操作统一经过现有 MCP 的确认逻辑。
        instructions = SYSTEM_PROMPT + "\n本程序只使用 mcp 的 mac 工具（由 Mac Controller 的 mac_tools.py 提供）操作 Mac 和读取文件；不要调用 ChatGPT Computer Use、cua_repl、浏览器插件、原生 shell 或 apply_patch。"
        config = codex_external_tool_overrides(self.workdir)
        config.update({
            "approval_policy": "never", "sandbox_mode": "read-only",
            "features.shell_tool": False, "base_instructions": instructions,
        })
        config["mcp_servers"]["mac"] = {
            "enabled": True, "required": True,
            # 本项目的工具在 mac_tools.confirm 中处理用户配置的操作确认。
            "default_tools_approval_mode": "approve",
            "command": executable,
            "args": args,
            "env": {"MAC_CTRL_SELF_PID": str(self.self_pid),
                                    "MAC_CTRL_CONFIRM": "1" if self.confirm else "0",
                                    "MAC_CTRL_CONFIRM_DELETE": "1" if self.confirm_delete else "0",
                                    "MAC_CTRL_WORKDIR": self.workdir, "PYTHONPATH": str(HERE)},
        }
        if self.reasoning_effort:
            config["model_reasoning_effort"] = self.reasoning_effort
        cmd = cli_prefix(CODEX, "@openai/codex", "bin/codex.js") + ["exec"]
        # TOML inline table 的键值用 =；字符串使用 JSON 转义（兼容 TOML 基本字符串）。
        def encode(value):
            if isinstance(value, dict):
                return "{" + ", ".join(f"{json.dumps(k)} = {encode(v)}" for k, v in value.items()) + "}"
            return json.dumps(value, ensure_ascii=False)

        for key, value in config.items():
            cmd += ["-c", f"{key}={encode(value)}"]
        if self.session_id:
            cmd += ["resume"]
        cmd += ["--json", "--skip-git-repo-check"]
        if self.model:
            cmd += ["--model", self.model]
        for file in files:
            if Path(file).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                cmd += ["--image", str(file)]
        if self.session_id:
            cmd += [self.session_id]
        return cmd + ["-"]

    def _handle_codex(self, ev):
        kind = ev.get("type")
        if kind == "thread.started":
            self.session_id = ev.get("thread_id") or self.session_id
        elif kind in {"item.started", "item.completed"}:
            item = ev.get("item", {})
            typ = item.get("type")
            if typ == "agent_message" and kind == "item.completed":
                if item.get("text", "").strip():
                    self.bridge.text.emit(item["text"])
            elif typ in {"mcp_tool_call", "command_execution"}:
                if kind == "item.started":
                    self.bridge.tool.emit(item.get("tool") or "run_shell",
                                          summarize_args(item.get("arguments")) if typ == "mcp_tool_call"
                                          else item.get("command", ""))
                else:
                    result = item.get("result") or {}
                    error = item.get("error")
                    failed = bool(error or result.get("isError") or item.get("status") == "failed"
                                  or item.get("exit_code", 0))
                    detail = str(error) if error else (_result_text(result.get("content")) if result
                                                      else item.get("aggregated_output", ""))
                    marker = "Computer Use was not approved to use "
                    if marker in detail:
                        failed = True
                        # _result_text 已将换行转成 ⏎，后面可能还附有工具说明。
                        target = detail.split(marker, 1)[1].split("⏎", 1)[0].split("##", 1)[0].strip()[:80]
                        self._access_denial = (
                            f"Computer Use 未获应用访问授权：{target}。"
                            "请在 ChatGPT 桌面客户端的设置 → Computer Use 中检查应用授权；"
                            "如需授权弹窗，请在该客户端发起访问任务并手动批准，然后重试。"
                            "微信登录状态与此授权无关。")
                        detail = self._access_denial
                    self.bridge.tool_result.emit(failed, detail[:200])
        elif kind in {"turn.failed", "error"}:
            err = ev.get("error") or ev.get("message") or "Codex 执行失败"
            return err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return None

    def _run(self):
        import tempfile
        started = time.monotonic()
        rounds = 0
        outcome = None
        try:
            while True:
                with self._lock:
                    if self._stopped:
                        return
                    if not self.pending:
                        outcome = f"完成 · {rounds} 轮 · {time.monotonic() - started:.0f} 秒"
                        return
                    prompt, self.workdir, files = self.pending.pop(0)
                    self._access_denial = None
                # stderr 写临时文件，避免长日志堵塞管道；从不把 prompt 放进命令行。
                with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
                    with self._lock:
                        if self._stopped:
                            return
                        proc = subprocess.Popen(self._command(files), cwd=self.workdir or str(Path.home()),
                                                env=external_env(),
                                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                                                text=True, encoding="utf-8", bufsize=1, start_new_session=True)
                        self.proc = proc
                    if self.model:
                        self.bridge.model.emit(self.model)
                    self.bridge.reasoning.emit(self.reasoning_effort or "默认（沿用 Codex 配置）")
                    proc.stdin.write(prompt)
                    proc.stdin.close()
                    failure = None
                    completed = False
                    for line in proc.stdout:
                        if self._stopped:
                            continue
                        try:
                            ev = json.loads(line)
                        except ValueError:
                            continue
                        failure = self._handle_codex(ev) or failure
                        completed = completed or ev.get("type") == "turn.completed"
                    proc.wait()
                    proc.stdout.close()
                    with self._lock:
                        if self.proc is proc:
                            self.proc = None
                    if self._stopped:
                        return
                    if self._access_denial:
                        raise RuntimeError(self._access_denial)
                    if proc.returncode or failure or not completed:
                        errors.seek(0)
                        raise RuntimeError(failure or errors.read()[-800:] or f"Codex 未完成（退出码 {proc.returncode}）")
                rounds += 1
        except FileNotFoundError:
            if not self._stopped:
                self.bridge.error.emit(f"找不到 codex 命令（{CODEX}），请先安装 Codex CLI 并执行 codex login。")
        except Exception as e:
            if not self._stopped:
                self.bridge.error.emit(f"Codex 执行失败：{e}")
        finally:
            with self._lock:
                self._kill()
                self.pending.clear()
                self.busy = False
            if 'proc' in locals():
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
                if proc.stdout and not proc.stdout.closed:
                    proc.stdout.close()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        terminate_process(proc, force=True)
                    except ProcessLookupError:
                        pass
                    proc.wait()
            if self._stopped and not self._silent:
                self.bridge.done.emit("已停止")
            elif outcome and not self._silent:
                self.bridge.done.emit(outcome)


# ---------------------------------------------------------------- Claude API

class ApiBackend:
    name = "Claude API"
    DEFAULT_MODEL = "claude-opus-5"

    def __init__(self, bridge, model="", confirm=True, self_pid=0, api_key="", confirm_delete=False):
        self.bridge = bridge
        self.model = model or self.DEFAULT_MODEL
        os.environ["MAC_CTRL_CONFIRM"] = "1" if confirm else "0"
        os.environ["MAC_CTRL_SELF_PID"] = str(self_pid)
        import platform_tools as mac_tools   # 环境变量要在导入前设好
        mac_tools.CONFIRM, mac_tools.SELF_PID = confirm, self_pid
        mac_tools.CONFIRM_DELETE = confirm_delete
        self.tools = mac_tools
        self.api_key = api_key
        self.messages = []
        self.pending = []            # 执行中新发来的消息，等当前这一步结束后一起交给模型
        self.busy = False
        self._stopped = False

    def state(self):
        """存盘用：截图的 base64 太大，换成占位文字。"""
        def strip(block):
            if block.get("type") in ("image", "document"):
                return {"type": "text", "text": "[附件内容已省略，原文件见消息里列出的路径]"}
            if block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                block = {**block, "content": [c if c.get("type") != "image" else {"type": "text", "text": "[截图已省略]"}
                                              for c in block["content"]]}
            return block
        msgs = [{**m, "content": [strip(b) for b in m["content"]]} if isinstance(m["content"], list) else m
                for m in self.messages]
        return {"messages": msgs} if msgs else {}

    def load(self, state):
        self.messages = list((state or {}).get("messages", []))

    def stop(self):
        self._stopped = True
        self.pending.clear()

    def shutdown(self):
        self.stop()

    def send(self, text, front_app=None, workdir="", files=()):
        self.tools.WORKDIR = workdir
        content = [{"type": "text", "text": context_note(front_app, workdir) + text + files_note(files, "内容已附在消息里")}]
        content += [b for f in files for b in self._file_blocks(Path(f))]
        if self.busy:                # 正在执行：排队，下一步时一起送进去
            self.pending.append(content)
            return
        self._stopped = False
        self.busy = True
        self.messages.append({"role": "user", "content": content})
        threading.Thread(target=self._run, daemon=True).start()

    def _take_pending(self):
        blocks = [b for c in self.pending for b in c]
        self.pending.clear()
        return blocks

    @staticmethod
    def _file_blocks(path):
        """图片 → image，PDF → document，文本 → text；其它类型只给路径，让模型自己用命令转换。"""
        import base64
        ext = path.suffix.lower()
        try:
            if ext in IMAGE_EXT:
                data = path.read_bytes()
                media = IMAGE_EXT[ext]
                if len(data) > 4_500_000:        # API 单张图上限约 5MB，缩小后再发
                    from io import BytesIO
                    from PIL import Image
                    img = Image.open(path).convert("RGB")
                    img.thumbnail((2400, 2400))
                    buf = BytesIO()
                    img.save(buf, "JPEG", quality=85)
                    data, media = buf.getvalue(), "image/jpeg"
                return [{"type": "image", "source": {"type": "base64", "media_type": media,
                                                     "data": base64.b64encode(data).decode()}}]
            if ext == ".pdf":
                return [{"type": "document", "title": path.name,
                         "source": {"type": "base64", "media_type": "application/pdf",
                                    "data": base64.b64encode(path.read_bytes()).decode()}}]
            if ext in TEXT_EXT:
                return [{"type": "text", "text": f"<file name=\"{path.name}\">\n"
                                                 f"{path.read_text(encoding='utf-8', errors='replace')[:200000]}\n</file>"}]
        except OSError as e:
            return [{"type": "text", "text": f"[读取 {path.name} 失败：{e}]"}]
        return []

    def _run(self):
        import anthropic
        try:
            client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else anthropic.Anthropic()
        except Exception as e:  # noqa: BLE001
            self.bridge.error.emit(f"无法创建 API 客户端：{e}（请设置 ANTHROPIC_API_KEY 或在设置里填写）")
            return
        tools = [{"name": n, "description": d, "input_schema": s} for n, _, d, s in self.tools.TOOLS]
        t0 = time.time()
        try:
            for step in range(MAX_STEPS):
                if self._stopped:
                    self.bridge.done.emit("已停止")
                    return
                resp = client.beta.messages.create(
                    model=self.model,
                    max_tokens=16000,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    thinking={"type": "adaptive"},
                    cache_control={"type": "ephemeral"},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                    messages=self.messages,
                )
                self.bridge.model.emit(resp.model)   # 触发拒绝兜底时可能换成别的模型
                if resp.stop_reason == "refusal":
                    self.bridge.error.emit("模型拒绝了这个请求。")
                    return
                # 转成普通 dict 保存（thinking 等块原样保留），这样可以存盘、下次接着聊
                self.messages.append({"role": "assistant",
                                      "content": [b.model_dump(mode="json", exclude_none=True) for b in resp.content]})
                calls = []
                for b in resp.content:
                    if b.type == "text" and b.text.strip():
                        self.bridge.text.emit(b.text)
                    elif b.type == "tool_use":
                        calls.append(b)
                if resp.stop_reason != "tool_use" or not calls:
                    if resp.stop_reason == "max_tokens":
                        self.bridge.error.emit("回复过长被截断。")
                        return
                    if self.pending:          # 答完了，但执行期间用户又发了消息：接着处理
                        self.messages.append({"role": "user", "content": self._take_pending()})
                        continue
                    self.bridge.done.emit(f"完成 · {step + 1} 轮 · {time.time() - t0:.0f} 秒")
                    return
                results = []
                for b in calls:   # 按顺序执行；停止后其余调用也要回一个结果，保持对话合法
                    if self._stopped:
                        results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                        "content": "用户已停止"})
                        continue
                    self.bridge.tool.emit(b.name, summarize_args(b.input))
                    parts, is_err = self.tools.run_tool(b.name, b.input)
                    self.bridge.tool_result.emit(is_err, _result_text(
                        [{"type": "text", "text": p[1]} if p[0] == "text" else {"type": "image"} for p in parts]))
                    content = [{"type": "text", "text": p[1]} if p[0] == "text" else
                               {"type": "image", "source": {"type": "base64", "media_type": p[2], "data": p[1]}}
                               for p in parts]
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": content,
                                    "is_error": is_err})
                self.messages.append({"role": "user", "content": results + self._take_pending()})
            self.bridge.error.emit(f"步数达到上限（{MAX_STEPS}），已停下。")
        except anthropic.AuthenticationError:
            self.bridge.error.emit("API Key 无效或未设置。可以改用「本机 Claude Code」后端。")
        except anthropic.RateLimitError:
            self.bridge.error.emit("触发了 API 速率限制，请稍后再试。")
        except anthropic.APIStatusError as e:
            self.bridge.error.emit(f"API 错误 {e.status_code}：{e.message}")
        except anthropic.APIConnectionError as e:
            self.bridge.error.emit(f"连接 API 失败：{e}")
        finally:
            self.busy = False
            self._repair()

    def _repair(self):
        """中途出错时，去掉末尾没有配对结果的 tool_use，保证下一轮对话仍然合法。"""
        last = self.messages[-1] if self.messages else None
        if last and last["role"] == "assistant" and any(
                b.get("type") == "tool_use" for b in last["content"]):
            self.messages.pop()
