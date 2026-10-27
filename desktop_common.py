"""Shared desktop tool safety checks and conversation notes."""
import os
import re
import subprocess
import time
from pathlib import Path
from i18n import tr, language

CONFIRM = os.environ.get("MAC_CTRL_CONFIRM", "1") == "1"
CONFIRM_DELETE = os.environ.get("MAC_CTRL_CONFIRM_DELETE", "0") == "1"
WORKDIR = os.environ.get("MAC_CTRL_WORKDIR", "")

class ToolError(Exception):
    pass

_W = r"(?<![\w./-])"

SHELL_RISKS = [
    (_W + r"(rm|rmdir|unlink|shred|srm)(?![\w-])", "删除文件"),
    (r"\bfind\b[^;&|]*\s-(delete|exec\s+rm)\b", "批量删除文件"),
    (r"\brsync\b[^;&|]*--delete", "同步时删除文件"),
    (_W + r"(sudo|su|doas)(?![\w-])", "管理员权限"),
    (_W + r"(dd|mkfs\S*|fdisk)(?![\w-])", "直接写磁盘"),
    (r"\bdiskutil\s+(erase\w*|partition\w*|zeroDisk|secureErase|apfs\s+delete\w*)", "抹掉/分区磁盘"),
    (_W + r"(kill|killall|pkill)(?![\w-])", "强制结束进程"),
    (_W + r"(shutdown|reboot|halt)(?![\w-])", "关机/重启"),
    (r"\blaunchctl\s+(unload|remove|bootout|disable)", "停用系统服务"),
    (r"\bgit\s+(push\b[^;&|]*(\s-f\b|--force)|reset\s+--hard|clean\s+-\w*f)", "不可恢复的 git 操作"),
    (r"\b(brew|pip3?|npm|conda)\s+(uninstall|remove)\b", "卸载软件"),
    (r"\b(defaults\s+delete|tccutil\s+reset|csrutil|spctl|pmset|networksetup\s+-set|security\s+delete)", "修改系统设置"),
    (r"\bch(mod|own)\s+(-\w*R|777)", "批量改权限"),
    (r"\bcrontab\s+-r\b", "删除定时任务"),
    (r"\bcurl\b[^;&|]*\s(-d|--data\S*|-F|--form|-T|--upload-file|-X\s*(POST|PUT|DELETE|PATCH))\b", "向网络发送数据"),
    (r"\b(mail|sendmail)\s", "发送邮件"),
]

SCRIPT_RISKS = [
    (r"\bdelete\b", "删除内容"),
    (r"\bempty\s+(the\s+)?trash\b", "清空废纸篓"),
    (r"\bsend\b", "发送消息/邮件"),
    (r"\bquit\b", "退出程序"),
    (r"\b(shut\s+down|restart|log\s+out)\b", "关机/重启/注销"),
    (r"administrator\s+privileges", "管理员权限"),
    (r"\berase\b", "抹掉内容"),
]

def risk_reasons(text, shell):
    """返回命中的风险说明（去重、按规则顺序）；为空表示可以直接执行。"""
    # 终端命令里嵌的 osascript 按 AppleScript 规则查；AppleScript 里的 do shell script 按终端规则查
    rules = []
    if shell or "do shell script" in text:
        rules += SHELL_RISKS
    if not shell or "osascript" in text:
        rules += SCRIPT_RISKS
    found = []
    for pattern, why in rules:
        if re.search(pattern, text, re.IGNORECASE) and why not in found:
            found.append(why)
    return found

def confirm_if_risky(title, text, shell):
    reasons = risk_reasons(text, shell)
    if not CONFIRM_DELETE:
        reasons = [why for why in reasons if why not in {"删除文件", "批量删除文件", "同步时删除文件", "删除内容"}]
    if reasons:
        detail = ("Detected: " + ", ".join(tr(reason) for reason in reasons) if language() == "en"
                  else "检测到：" + "、".join(reasons))
        confirm(title, f"{detail}\n\n{text}")

def workdir():
    d = Path(WORKDIR) if WORKDIR else Path.home() / "Documents" / "Mac 控制台" / "未归档"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _note_path(name):
    name = re.sub(r"[\\/:]+", "_", (name or "").strip()) or "笔记"
    if not name.lower().endswith((".md", ".txt")):
        name += ".md"
    return workdir() / name

def t_note_write(name, content, append=True):
    p = _note_path(name)
    had = p.exists() and p.stat().st_size > 0
    with open(p, "a" if append else "w", encoding="utf-8") as f:
        if append and had:
            f.write("\n\n")
        f.write(content.rstrip() + "\n")
    return f"已{'追加到' if append and had else '写入'}笔记「{p.name}」（共 {p.stat().st_size} 字节）：{p}"

def t_note_read(name, max_chars=30000):
    p = _note_path(name)
    if not p.exists():
        raise ToolError(f"没有笔记「{p.name}」。可用 note_list 查看已有文件。")
    s = p.read_text(encoding="utf-8", errors="replace")
    return s if len(s) <= max_chars else s[:max_chars] + f"\n…（后面还有 {len(s) - max_chars} 字）"

def t_note_list():
    d = workdir()
    files = sorted((p for p in d.rglob("*") if p.is_file() and not any(x.startswith(".") for x in p.relative_to(d).parts)),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return f"工作文件夹 {d} 里还没有文件。"
    lines = [f"工作文件夹：{d}"]
    for p in files[:200]:
        st = p.stat()
        lines.append(f"- {p.relative_to(d)}  {st.st_size // 1024 or 1} KB  {time.strftime('%m-%d %H:%M', time.localtime(st.st_mtime))}")
    if len(files) > 200:
        lines.append(f"…共 {len(files)} 个文件")
    return "\n".join(lines)

def _schema(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}

XY = {"x": {"type": "integer"}, "y": {"type": "integer"}}
