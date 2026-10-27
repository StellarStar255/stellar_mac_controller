"""Windows UI Automation and cross-platform X11/Windows desktop tools.

Desktop control on Linux requires an unlocked X11 session. Wayland is explicitly
reported as unavailable instead of silently sending input to the wrong surface.
"""
import base64
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import desktop_common as common
from desktop_common import ToolError, _schema, XY, risk_reasons

CONFIRM = os.environ.get("MAC_CTRL_CONFIRM", "1") == "1"
CONFIRM_DELETE = os.environ.get("MAC_CTRL_CONFIRM_DELETE", "0") == "1"
SELF_PID = int(os.environ.get("MAC_CTRL_SELF_PID", "0") or 0)
WORKDIR = os.environ.get("MAC_CTRL_WORKDIR", "")
_ELEMENTS = {}
_SCALE = 1.0


def _sync():
    common.CONFIRM, common.CONFIRM_DELETE, common.WORKDIR = CONFIRM, CONFIRM_DELETE, WORKDIR
    common.confirm = confirm


def _qt():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def confirm(title, detail):
    if not CONFIRM:
        return
    args = [sys.executable] + (["--confirm"] if getattr(sys, "frozen", False)
                              else [str(Path(__file__).with_name("launcher.py")), "--confirm"])
    result = subprocess.run(args, input=json.dumps({"title": title, "detail": detail[:1500]}),
                            text=True, capture_output=True, timeout=600)
    if result.returncode:
        raise ToolError("用户拒绝了这个操作，请停止。")


def confirm_if_risky(title, text, shell):
    _sync()
    common.confirm_if_risky(title, text, shell)
    if re.search(r'(?i)\b(Remove-Item|Stop-Process|Stop-Computer|Restart-Computer|Clear-RecycleBin|Format-Volume|del|erase)\b', text):
        confirm(title, text)


def permissions():
    available = sys.platform == "win32" or (bool(os.environ.get("DISPLAY")) and os.environ.get("XDG_SESSION_TYPE") != "wayland")
    return {"accessibility": available, "screen_recording": available}


def permission_hint(missing):
    return ("Windows 请保持桌面解锁；普通权限进程不能操作以管理员身份运行的窗口。" if sys.platform == "win32"
            else "Linux 电脑操作需要已解锁的 X11 桌面；Wayland 暂不支持。请在登录界面选择 Xorg/X11 会话。命令和笔记仍可使用。")


def _gui():
    if not permissions()["accessibility"]:
        raise ToolError(permission_hint([]))
    import pyautogui
    pyautogui.FAILSAFE = True
    return pyautogui


def _windows():
    import pygetwindow
    return [w for w in pygetwindow.getAllWindows() if w.title]


def running_apps():
    if sys.platform == "win32":
        return [{"name": w.title, "pid": int(w._hWnd)} for w in _windows()]
    if not os.environ.get("DISPLAY"):
        return []
    result = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=5)
    return [{"name": columns[4], "pid": int(columns[0], 16)}
            for line in result.stdout.splitlines() if len(columns := line.split(None, 4)) == 5]


def frontmost_app():
    try:
        if sys.platform == "win32":
            import pygetwindow
            w = pygetwindow.getActiveWindow()
            if w:
                import ctypes
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(w._hWnd, ctypes.byref(pid))
                if pid.value == SELF_PID:
                    return None
            return {"name": w.title, "pid": int(w._hWnd)} if w else None
        result = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True, timeout=3)
        handle = int(result.stdout.strip())
        return next((a for a in running_apps() if a["pid"] == handle), None)
    except (OSError, ValueError):
        return None


def t_list_apps(include_installed=False):
    return "正在运行的窗口：\n" + "\n".join(f"- {a['name']}" for a in running_apps())


def t_open(target, app=None):
    if app:
        subprocess.Popen([app, target])
    elif re.match(r"https?://", target):
        import webbrowser
        webbrowser.open(target)
    elif Path(target).expanduser().exists():
        path = str(Path(target).expanduser().resolve())
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])
    else:
        subprocess.Popen([target])
    return "已打开：" + target


def t_activate_app(name):
    if sys.platform == "win32":
        for window in _windows():
            if name.casefold() in window.title.casefold():
                if window.isMinimized:
                    window.restore()
                window.activate()
                return "已切换到：" + window.title
    else:
        p = subprocess.run(["wmctrl", "-a", name], capture_output=True, text=True, timeout=5)
        if p.returncode == 0:
            return "已切换到：" + name
    raise ToolError("没有找到目标窗口，请先使用 open 启动程序，或用 list_apps 确认窗口名称。")


def t_quit_app(name):
    confirm("退出程序", name)
    t_activate_app(name)
    _gui().hotkey("alt", "f4")
    return "已请求关闭：" + name


def t_run_shell(command, timeout=120):
    confirm_if_risky("运行命令", command, shell=True)
    _sync()
    p = subprocess.run(command, shell=True, capture_output=True, text=True,
                       timeout=min(max(int(timeout), 1), 600), cwd=str(common.workdir()))
    return f"退出码 {p.returncode}\n{(p.stdout + p.stderr)[:12000]}"


def t_read_ui(app=None, max_elements=200, include_menu_bar=False):
    _ELEMENTS.clear()
    if sys.platform != "win32":
        return "Linux 当前版本不提供辅助功能树；请用 screenshot 查看，再按截图坐标操作。"
    from pywinauto import Desktop
    if app:
        t_activate_app(app)
    import ctypes
    window = Desktop(backend="uia").window(handle=ctypes.windll.user32.GetForegroundWindow())
    lines = []
    for control in window.descendants()[:max_elements]:
        try:
            if not control.is_visible():
                continue
            rect = control.rectangle()
            eid = len(_ELEMENTS) + 1
            _ELEMENTS[eid] = control
            name = "[密码框]" if control.element_info.control_type == "Edit" and control.element_info.element.CurrentIsPassword else control.window_text()
            lines.append(f"[{eid}] {control.element_info.control_type} {name[:100]} @({rect.mid_point().x},{rect.mid_point().y})")
        except Exception:
            continue
    return "\n".join(lines) or "没有读到界面元素，请使用 screenshot。"


def t_ui_action(id, action="press", text=None):
    control = _ELEMENTS.get(id)
    if control is None:
        raise ToolError("编号失效，请重新 read_ui。")
    if action == "set_text":
        if control.element_info.element.CurrentIsPassword:
            raise ToolError("不向密码框输入。")
        control.set_edit_text(text or "")
    elif action == "focus":
        control.set_focus()
    elif action == "show_menu":
        control.click_input(button="right")
    elif action == "press" and hasattr(control, "invoke"):
        control.invoke()
    else:
        control.click_input()
    return "操作完成，请重新读取界面确认。"


def t_screenshot(mark_elements=False):
    global _SCALE
    if not permissions()["screen_recording"]:
        raise ToolError(permission_hint([]))
    import mss
    from PIL import Image
    with mss.mss() as capture:
        shot = capture.grab(capture.monitors[1])
        image = Image.frombytes("RGB", shot.size, shot.rgb)
    w, h = image.size
    _SCALE = min(1, 1568 / max(w, h), math.sqrt(1150000 / (w * h)))
    image = image.resize((round(w * _SCALE), round(h * _SCALE)))
    output = io.BytesIO()
    image.save(output, "JPEG", quality=80)
    return [("text", f"主屏幕截图 {image.width}×{image.height}，可直接使用图中坐标。"),
            ("image", base64.b64encode(output.getvalue()).decode(), "image/jpeg")]


def _point(x, y):
    gui = _gui()
    x, y = round(x / _SCALE), round(y / _SCALE)
    if not gui.onScreen(x, y):
        raise ToolError("坐标超出主屏幕。")
    return x, y


def _key(key):
    return {"cmd": "ctrl", "command": "ctrl", "super": "win", "return": "enter", "esc": "esc", "option": "alt"}.get(key, key)


def t_click(x, y, button="left", clicks=1, modifiers=None):
    gui = _gui()
    keys = [_key(k) for k in (modifiers or [])]
    try:
        for key in keys:
            gui.keyDown(key)
        gui.click(*_point(x, y), button=button, clicks=min(max(clicks, 1), 2), interval=0.1)
    finally:
        for key in reversed(keys):
            gui.keyUp(key)
    return "已点击。"


def t_drag(x1, y1, x2, y2):
    gui = _gui()
    gui.moveTo(*_point(x1, y1))
    gui.dragTo(*_point(x2, y2), duration=0.6)
    return "已拖动。"


def t_type_text(text):
    import pyperclip
    previous = pyperclip.paste()
    pyperclip.copy(text)
    _gui().hotkey("ctrl", "v")
    time.sleep(0.3)
    pyperclip.copy(previous)
    return "已输入文字，未按回车。"


def t_press_key(keys, repeat=1):
    gui = _gui()
    for _ in range(min(max(repeat, 1), 30)):
        gui.hotkey(*[_key(k.strip().lower()) for k in keys.split("+")])
    return "已按键。"


def t_scroll(x, y, direction="down", amount=3):
    gui = _gui()
    gui.moveTo(*_point(x, y))
    amount = min(max(int(amount), 1), 100)
    if direction in {"left", "right"}:
        gui.hscroll(amount if direction == "right" else -amount)
    else:
        gui.scroll(amount if direction == "up" else -amount)
    return "已滚动。"


def t_wait(seconds=1):
    time.sleep(min(max(seconds, 0), 30))
    return "等待完成。"


def t_note_write(name, content, append=True):
    _sync()
    return common.t_note_write(name, content, append)


def t_note_read(name, max_chars=30000):
    _sync()
    return common.t_note_read(name, max_chars)


def t_note_list():
    _sync()
    return common.t_note_list()


def run_tool(name, args):
    fn = TOOL_MAP.get(name)
    if fn is None:
        return [("text", f"未知工具：{name}")], True
    try:
        output = fn(**(args or {}))
        return (output if isinstance(output, list) else [("text", str(output))]), False
    except Exception as error:
        return [("text", f"{type(error).__name__}: {error}")], True
TOOLS = [('list_apps', t_list_apps, '列出正在运行的程序和最前面的程序；include_installed=true 时同时列出已安装的程序。', _schema({'include_installed': {'type': 'boolean'}})), ('open', t_open, '打开程序、文件、文件夹或网址。target 可以是程序名（如 "备忘录"、"Safari"）、路径或 URL；给 app 时用该程序打开 target。', _schema({'target': {'type': 'string'}, 'app': {'type': 'string'}}, ['target'])), ('activate_app', t_activate_app, '把某个程序切到最前面（没运行则启动）。键盘输入前务必先切到目标程序。', _schema({'name': {'type': 'string'}}, ['name'])), ('quit_app', t_quit_app, '退出一个程序。', _schema({'name': {'type': 'string'}}, ['name'])), ('run_shell', t_run_shell, '运行 zsh 命令并返回输出（文件操作、下载、查询系统信息等）。当前目录是本对话的工作文件夹；耗时很长的批量任务请放到后台（nohup … &）并把进度写到工作文件夹里的日志。', _schema({'command': {'type': 'string'}, 'timeout': {'type': 'integer'}}, ['command'])), ('read_ui', t_read_ui, '读取某个程序（默认最前面的程序）当前界面的辅助功能树，返回带编号的元素列表：[编号] 类型 "名称" 值 [状态] @(中心坐标)。之后用 ui_action 按编号操作。界面改变后编号失效，需重新读取。include_menu_bar=true 时附带菜单栏的全部菜单项。', _schema({'app': {'type': 'string'}, 'max_elements': {'type': 'integer'}, 'include_menu_bar': {'type': 'boolean'}})), ('ui_action', t_ui_action, '按 read_ui 的编号操作元素。action: press（按下按钮/菜单项/复选框等，首选）、click（鼠标点击中心）、show_menu（右键菜单）、focus（聚焦）、set_text（在输入框填入 text，会覆盖原内容，不会按回车）。', _schema({'id': {'type': 'integer'}, 'action': {'type': 'string', 'enum': ['press', 'click', 'show_menu', 'focus', 'set_text']}, 'text': {'type': 'string'}}, ['id'])), ('screenshot', t_screenshot, '截取主屏幕。读不到界面元素、或需要看图片/画面内容时使用。mark_elements=true 会把上次 read_ui 的编号画在图上。', _schema({'mark_elements': {'type': 'boolean'}})), ('click', t_click, '在截图坐标 (x,y) 处点击。button: left/right/middle；clicks: 1 或 2（双击）；modifiers 如 ["cmd"]。', _schema({**XY, 'button': {'type': 'string', 'enum': ['left', 'right', 'middle']}, 'clicks': {'type': 'integer'}, 'modifiers': {'type': 'array', 'items': {'type': 'string'}}}, ['x', 'y'])), ('drag', t_drag, '按住左键从 (x1,y1) 拖到 (x2,y2)。', _schema({k: {'type': 'integer'} for k in ('x1', 'y1', 'x2', 'y2')}, ['x1', 'y1', 'x2', 'y2'])), ('type_text', t_type_text, '在当前焦点处输入文字（通过粘贴输入，不受中文输入法影响，支持中文和换行）。不会按回车。需要提交时再单独调用 press_key("return")。', _schema({'text': {'type': 'string'}}, ['text'])), ('press_key', t_press_key, '按键或组合键，如 "return"、"esc"、"cmd+c"、"cmd+shift+4"、"down"。', _schema({'keys': {'type': 'string'}, 'repeat': {'type': 'integer'}}, ['keys'])), ('scroll', t_scroll, '在 (x,y) 处滚动。direction: up/down/left/right；amount 为行数。', _schema({**XY, 'direction': {'type': 'string', 'enum': ['up', 'down', 'left', 'right']}, 'amount': {'type': 'integer'}}, ['x', 'y', 'direction'])), ('note_write', t_note_write, '把调研结论、要点、来源链接、待办写进本对话工作文件夹里的笔记（Markdown）。默认追加；append=false 为整篇覆盖（用于整理最终版）。关闭程序后也会保留，下次继续时可以读回来。', _schema({'name': {'type': 'string', 'description': '笔记文件名，如 "调研笔记"、"总结"'}, 'content': {'type': 'string'}, 'append': {'type': 'boolean'}}, ['name', 'content'])), ('note_read', t_note_read, '读取本对话工作文件夹里的一篇笔记或文本文件。', _schema({'name': {'type': 'string'}, 'max_chars': {'type': 'integer'}}, ['name'])), ('note_list', t_note_list, '列出本对话工作文件夹里的笔记和文件（含下载的文件）。继续之前的任务时先看一下。', _schema({})), ('wait', t_wait, '等待若干秒（等页面/程序加载）。', _schema({'seconds': {'type': 'number'}}, ['seconds']))]
# The same call schemas work on all desktop platforms. Platform-specific tools
# are deliberately absent, so the model cannot accidentally use AppleScript.
TOOLS = [(name, fn, description.replace("zsh", "系统终端").replace("Mac", "电脑"), schema)
         for name, fn, description, schema in TOOLS]
TOOL_MAP = {name: fn for name, fn, _, _ in TOOLS}
