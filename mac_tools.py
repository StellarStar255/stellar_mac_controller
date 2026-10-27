"""操作 Mac 的工具集：两种后端（本机 Claude Code 的 MCP 服务 / Claude API）共用这一份实现。

思路借鉴 Jev 类的 computer-use：优先读取「辅助功能树」把界面元素编号，按编号操作（快、准、不用截图）；
读不到元素时再退回截图 + 坐标点击。

坐标约定：所有暴露给模型的坐标都在「模型坐标系」里 —— 主屏幕逻辑坐标 × SCALE，
截图也按同一比例缩放，所以截图上的像素位置可以直接拿来 click。
"""
import base64
import io
import json
import math
import os
import re
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import ApplicationServices as AX
import Quartz
from AppKit import NSRunningApplication, NSWorkspace, NSApplicationActivateIgnoringOtherApps

# ---------------------------------------------------------------- 基础设施

SELF_PID = int(os.environ.get("MAC_CTRL_SELF_PID", "0") or 0)   # 控制台窗口自己的进程，读界面时跳过
CONFIRM = os.environ.get("MAC_CTRL_CONFIRM", "1") == "1"         # 危险操作前弹窗确认
CONFIRM_DELETE = os.environ.get("MAC_CTRL_CONFIRM_DELETE", "0") == "1"  # 删除单独设置
WORKDIR = os.environ.get("MAC_CTRL_WORKDIR", "")                  # 本对话的工作文件夹（笔记、下载默认放这）


class ToolError(Exception):
    pass


def _screen_size():
    b = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    return b.size.width, b.size.height


def _model_scale():
    w, h = _screen_size()
    return min(1.0, 1568 / max(w, h), math.sqrt(1_150_000 / (w * h)))


SCALE = _model_scale()


def to_model(x, y):
    return round(x * SCALE), round(y * SCALE)


def to_screen(x, y):
    return x / SCALE, y / SCALE


def _osascript(script, timeout=60):
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise ToolError(p.stderr.strip() or f"osascript 退出码 {p.returncode}")
    return p.stdout.strip()


def _as_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# 只有命中这些规则的命令/脚本才弹窗确认；打开、查看、下载、移动等日常操作直接执行
_W = r"(?<![\w./-])"      # 命令词前面不能紧挨字母、路径或 “-”（避免 --rm、form 之类误判）
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
        confirm(title, f"检测到：{'、'.join(reasons)}\n\n{text}")


def confirm(title, detail):
    """危险操作前弹原生对话框让用户确认。关闭确认模式时直接放行。"""
    if not CONFIRM:
        return
    detail = detail if len(detail) < 1500 else detail[:1500] + "\n…"
    script = (f"display dialog {_as_str(detail)} with title {_as_str('Mac 控制台 · ' + title)} "
              f'buttons {{"拒绝", "允许"}} default button "允许" cancel button "拒绝" with icon caution')
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        raise ToolError("用户拒绝了这个操作。请停下来问用户接下来怎么做。")


def permissions():
    return {"accessibility": bool(AX.AXIsProcessTrusted()),
            "screen_recording": bool(Quartz.CGPreflightScreenCaptureAccess())}


def responsible_app():
    """系统按谁来判定本进程的隐私权限（「负责进程」）：从终端启动时是那个终端 App，
    不是 Python。返回 App 名（如 "Stellar Smart Terminal"），查不到返回 None。"""
    try:
        import ctypes
        lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        get = lib.responsibility_get_pid_responsible_for_pid
        get.argtypes, get.restype = [ctypes.c_int], ctypes.c_int
        pid = get(os.getpid())
        if pid <= 0:
            return None
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None and app.localizedName():
            return str(app.localizedName())
        buf = ctypes.create_string_buffer(4096)
        if lib.proc_pidpath(pid, buf, 4096) > 0:
            path = buf.value.decode("utf-8", "replace")
            m = re.search(r"([^/]+)\.app/", path)
            return m.group(1) if m else os.path.basename(path)
    except Exception:       # noqa: BLE001 — 私有接口，拿不到就退回笼统说法
        pass
    return None


def permission_hint(missing):
    """缺权限时给用户的说明：点名要授权的 App，并讲清两个常见坑。"""
    who = responsible_app()
    target = f"「{who}」" if who else "启动本程序的终端（或 Python）"
    restart = f"完全退出并重新打开 {who}" if who else "完全退出并重新打开那个终端"
    parts = [f"缺少「{'」「'.join(missing)}」权限：请在 系统设置 → 隐私与安全性 里给{target}打开开关。"]
    if "屏幕录制" in missing:
        parts.append(f"屏幕录制要{restart}才生效，只重启本程序不够。")
    parts.append("开关已打开仍无效：多半是旧版本留下的授权记录，选中它点「−」删掉后重新添加"
                 "（或终端执行 tccutil reset Accessibility / ScreenCapture 加上该 App 的 bundle id）。"
                 "没有权限时只能用 AppleScript/命令。")
    return "".join(parts)


# ---------------------------------------------------------------- 程序

def _app_dirs():
    return [Path("/Applications"), Path("/System/Applications"), Path("/System/Applications/Utilities"),
            Path("/Applications/Utilities"), Path.home() / "Applications"]


def installed_apps():
    names = set()
    for d in _app_dirs():
        if d.is_dir():
            for p in d.glob("*.app"):
                names.add(p.stem)
            for p in d.glob("*/*.app"):
                names.add(p.stem)
    return sorted(names, key=str.lower)


def running_apps():
    out = []
    for a in NSWorkspace.sharedWorkspace().runningApplications():
        if a.activationPolicy() == 0 and a.processIdentifier() != SELF_PID:   # 0 = 普通有 Dock 图标的程序
            out.append({"name": a.localizedName(), "pid": a.processIdentifier(),
                        "bundle_id": a.bundleIdentifier(), "hidden": bool(a.isHidden())})
    return out


def _find_running(name):
    name_l = name.lower()
    apps = running_apps()
    for a in apps:
        if a["name"].lower() == name_l or (a["bundle_id"] or "").lower() == name_l:
            return a
    for a in apps:
        if name_l in a["name"].lower():
            return a
    return None


def frontmost_app():
    """当前焦点所在的程序（跳过控制台自己）。
    先问辅助功能「焦点在哪个程序」；拿不到或焦点在控制台上时，按窗口前后顺序找，
    并跳过透明窗口和很小的窗口（比如「预览」常挂着一个看不见的窗口）。"""
    if AX.AXIsProcessTrusted():
        err, focused = AX.AXUIElementCopyAttributeValue(AX.AXUIElementCreateSystemWide(), "AXFocusedApplication", None)
        if err == 0 and focused is not None:
            err, pid = AX.AXUIElementGetPid(focused, None)
            if err == 0 and pid != SELF_PID:
                app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                if app is not None and app.activationPolicy() == 0:
                    return {"name": app.localizedName(), "pid": pid}
    sw, sh = _screen_size()
    opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
        pid = w.get("kCGWindowOwnerPID")
        b = w.get("kCGWindowBounds") or {}
        x, y, ww, wh = b.get("X", 0), b.get("Y", 0), b.get("Width", 0), b.get("Height", 0)
        if (w.get("kCGWindowLayer", 1) != 0 or pid == SELF_PID or w.get("kCGWindowAlpha", 1) < 0.05
                or ww < 80 or wh < 60
                or x + ww <= 0 or y + wh <= 0 or x >= sw or y >= sh):   # 台前调度把其它窗口缩成屏幕外的缩略图
            continue
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None and app.activationPolicy() == 0:
            return {"name": app.localizedName(), "pid": pid}
    return None


def t_list_apps(include_installed=False):
    lines = ["正在运行："]
    for a in running_apps():
        lines.append(f"- {a['name']} ({a['bundle_id']})" + (" [已隐藏]" if a["hidden"] else ""))
    front = frontmost_app()
    if front:
        lines.append(f"\n最前面的程序：{front['name']}")
    if include_installed:
        lines.append("\n已安装：" + "、".join(installed_apps()))
    return "\n".join(lines)


def t_open(target, app=None):
    cmd = ["open"]
    if app:
        cmd += ["-a", app]
    if target:
        looks_like_path_or_url = bool(re.match(r"^[A-Za-z][\w+.-]*:", target)) or target.startswith(("/", "~", "./"))
        if looks_like_path_or_url:
            cmd.append(os.path.expanduser(target))
        elif not app:
            cmd = ["open", "-a", target]
        else:
            cmd.append(target)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise ToolError(p.stderr.strip() or "打开失败")
    time.sleep(0.8)
    return f"已打开：{' '.join(cmd[1:])}"


def t_activate_app(name):
    a = _find_running(name)
    if not a:
        return t_open(name)
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(a["pid"])
    app.unhide()
    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    time.sleep(0.4)
    return f"已切换到 {a['name']}"


def t_quit_app(name):
    confirm("退出程序", f"要退出「{name}」吗？未保存的内容可能会提示保存。")
    _osascript(f"tell application {_as_str(name)} to quit")
    return f"已请求退出 {name}"


def t_run_applescript(script):
    confirm_if_risky("运行 AppleScript", script, shell=False)
    out = _osascript(script, timeout=120)
    return out[:8000] if out else "（执行成功，无输出）"


def t_run_shell(command, timeout=120):
    confirm_if_risky("运行终端命令", command, shell=True)
    p = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=min(int(timeout), 600),
                       cwd=str(workdir()))
    out = (p.stdout + ("\n[stderr]\n" + p.stderr if p.stderr.strip() else "")).strip()
    if len(out) > 12000:
        out = out[:6000] + "\n…（中间省略）…\n" + out[-6000:]
    return f"退出码 {p.returncode}\n{out}"


# ---------------------------------------------------------------- 辅助功能树（Jev 式：元素编号 → 按编号操作）

ACTIONABLE = {"AXButton", "AXTextField", "AXTextArea", "AXSearchField", "AXCheckBox", "AXRadioButton",
              "AXPopUpButton", "AXMenuButton", "AXComboBox", "AXLink", "AXMenuItem", "AXMenuBarItem",
              "AXSlider", "AXIncrementor", "AXDisclosureTriangle", "AXTab", "AXCell", "AXRow",
              "AXImage", "AXColorWell", "AXSegmentedControl", "AXDockItem"}
ROLE_CN = {"AXButton": "按钮", "AXTextField": "输入框", "AXTextArea": "文本区", "AXSearchField": "搜索框",
           "AXCheckBox": "复选框", "AXRadioButton": "单选/标签页", "AXPopUpButton": "下拉框", "AXMenuButton": "菜单按钮",
           "AXComboBox": "组合框", "AXLink": "链接", "AXMenuItem": "菜单项", "AXMenuBarItem": "菜单栏",
           "AXSlider": "滑块", "AXStaticText": "文字", "AXImage": "图片", "AXCell": "单元格", "AXRow": "行",
           "AXTab": "标签页", "AXWindow": "窗口", "AXDisclosureTriangle": "展开箭头", "AXHeading": "标题",
           "AXWebArea": "网页", "AXTable": "表格", "AXList": "列表", "AXOutline": "大纲列表", "AXSheet": "弹出面板"}
TEXT_INPUT = {"AXTextField", "AXTextArea", "AXSearchField", "AXComboBox"}

_ELEMENTS = {}      # id -> dict(el, role, label, frame, pid)，每次 read_ui 重建


def _attr(el, name):
    err, val = AX.AXUIElementCopyAttributeValue(el, name, None)
    return val if err == 0 else None


def _axvalue(v, kind):
    if v is None:
        return None
    try:
        ok, val = AX.AXValueGetValue(v, kind, None)
        if ok:
            return val
    except Exception:
        pass
    nums = [float(n) for n in re.findall(r"[-\d.]+", str(v).split("}")[-1] or str(v))]
    return nums[-2:] if len(nums) >= 2 else None


def _frame(el):
    p = _axvalue(_attr(el, "AXPosition"), getattr(AX, "kAXValueCGPointType", 1))
    s = _axvalue(_attr(el, "AXSize"), getattr(AX, "kAXValueCGSizeType", 2))
    if p is None or s is None:
        return None
    px, py = (p.x, p.y) if hasattr(p, "x") else p
    sw, sh = (s.width, s.height) if hasattr(s, "width") else s
    return px, py, sw, sh


def _short(v, n=80):
    if v is None:
        return ""
    s = str(v).replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def _label(el):
    for a in ("AXTitle", "AXDescription", "AXHelp"):
        v = _attr(el, a)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _app_element(pid):
    app = AX.AXUIElementCreateApplication(pid)
    AX.AXUIElementSetMessagingTimeout(app, 1.5)
    # Chrome / Electron 类程序需要主动打开辅助功能树
    AX.AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)
    return app


def t_read_ui(app=None, max_elements=200, include_menu_bar=False):
    if not AX.AXIsProcessTrusted():
        raise ToolError(permission_hint(["辅助功能"]))
    target = _find_running(app) if app else frontmost_app()
    if not target:
        raise ToolError(f"找不到正在运行的程序：{app}" if app else "找不到前台程序")
    pid = target["pid"]
    appel = _app_element(pid)
    sw, sh = _screen_size()
    _ELEMENTS.clear()
    lines = []
    budget = {"visit": 4000, "emit": int(max_elements)}

    def emit(el, role, depth, frame, extra=""):
        eid = len(_ELEMENTS) + 1
        label = _label(el)
        _ELEMENTS[eid] = {"el": el, "role": role, "label": label, "frame": frame, "pid": pid}
        parts = [f"[{eid}]", ROLE_CN.get(role, role.replace("AX", ""))]
        if label:
            parts.append(f'"{_short(label)}"')
        parts.append(extra)
        if frame:
            x, y = to_model(frame[0] + frame[2] / 2, frame[1] + frame[3] / 2)
            parts.append(f"@({x},{y})")
        lines.append("  " * min(depth, 8) + " ".join(p for p in parts if p))
        budget["emit"] -= 1

    def walk(el, depth, in_menu=False):
        if budget["visit"] <= 0 or budget["emit"] <= 0 or depth > 40:
            return
        budget["visit"] -= 1
        role = _attr(el, "AXRole") or ""
        subrole = _attr(el, "AXSubrole") or ""
        frame = None if in_menu else _frame(el)
        if frame and not in_menu:
            x, y, w, h = frame
            if w <= 1 or h <= 1 or x + w < 0 or y + h < 0 or x > sw * 3 or y > sh * 2:
                if role not in ("AXWindow", "AXApplication"):
                    return
        flags = []
        if _attr(el, "AXEnabled") is False:
            flags.append("不可用")
        if _attr(el, "AXFocused"):
            flags.append("焦点")
        if _attr(el, "AXSelected"):
            flags.append("已选中")
        if subrole == "AXSecureTextField":
            flags.append("密码框")
        extra = ""
        if role in TEXT_INPUT or role in ("AXCheckBox", "AXRadioButton", "AXSlider", "AXPopUpButton"):
            v = _attr(el, "AXValue")
            if subrole != "AXSecureTextField" and v not in (None, ""):
                extra += f'值="{_short(v, 60)}" '
            ph = _attr(el, "AXPlaceholderValue")
            if ph:
                extra += f'提示="{_short(ph, 40)}" '
        if flags:
            extra += "[" + ",".join(flags) + "]"
        if role == "AXStaticText":
            v = _attr(el, "AXValue") or _label(el)
            if v and str(v).strip():
                emit(el, role, depth, frame, f'"{_short(v, 120)}"')
            return
        if role in ACTIONABLE or role in ("AXWindow", "AXSheet", "AXWebArea", "AXHeading") \
                or (role in ("AXGroup", "AXToolbar") and _label(el)):
            emit(el, role, depth, frame, extra.strip())
        for child in _attr(el, "AXChildren") or []:
            walk(child, depth + 1, in_menu or role in ("AXMenuBar", "AXMenu"))

    windows = list(_attr(appel, "AXWindows") or [])
    focused = _attr(appel, "AXFocusedWindow")
    if focused is not None:
        windows.sort(key=lambda w: 0 if w == focused else 1)
    lines.append(f"程序：{target['name']}（坐标可直接用于 click，与截图一致）")
    if target["name"] in BROWSERS:
        lines.append("提示：这是浏览器，网页内容请改用 web_read / web_act，更快更准。")
    for w in windows[:4]:
        walk(w, 0)
    if include_menu_bar:
        mb = _attr(appel, "AXMenuBar")
        if mb is not None:
            budget["emit"] = max(budget["emit"], 250)
            lines.append("—— 菜单栏（菜单项可直接 press，无需先展开）——")
            walk(mb, 0, in_menu=True)
    if not windows:
        lines.append("（这个程序没有可见窗口）")
    if budget["emit"] <= 0:
        lines.append("…元素过多已截断；可调大 max_elements，或配合截图。")
    if len(_ELEMENTS) <= 2:
        lines.append("（几乎读不到元素：这个程序可能不支持辅助功能，请改用 screenshot + click）")
    return "\n".join(lines)


def _get_element(eid):
    info = _ELEMENTS.get(int(eid))
    if not info:
        raise ToolError(f"没有编号 {eid} 的元素，请先调用 read_ui 重新读取界面。")
    if _attr(info["el"], "AXRole") is None:   # 执行前重新核对：元素已消失则拒绝，避免点错
        raise ToolError(f"元素 {eid} 已经不存在了（界面变了），请重新 read_ui。")
    return info


def _center(info):
    f = _frame(info["el"]) or info["frame"]
    if not f:
        raise ToolError("这个元素没有位置信息，无法用鼠标点击。")
    return f[0] + f[2] / 2, f[1] + f[3] / 2


def t_ui_action(id, action="press", text=None):
    info = _get_element(id)
    el, role = info["el"], info["role"]
    desc = f"{ROLE_CN.get(role, role)} \"{_short(info['label'], 40)}\""
    secure = _attr(el, "AXSubrole") == "AXSecureTextField"
    if action == "press":
        if AX.AXUIElementPerformAction(el, "AXPress") == 0:
            time.sleep(0.3)
            return f"已按下 {desc}"
        _mouse_click(*_center(info))
        return f"{desc} 不支持直接按下，已改为鼠标点击其中心"
    if action == "click":
        _mouse_click(*_center(info))
        return f"已鼠标点击 {desc}"
    if action == "show_menu":
        if AX.AXUIElementPerformAction(el, "AXShowMenu") != 0:
            _mouse_click(*_center(info), button="right")
        return f"已打开 {desc} 的右键菜单"
    if action == "focus":
        AX.AXUIElementSetAttributeValue(el, "AXFocused", True)
        return f"已聚焦 {desc}"
    if action == "set_text":
        if secure:
            raise ToolError("出于安全考虑，不会向密码框输入内容，请让用户自己输入。")
        if text is None:
            raise ToolError("set_text 需要 text 参数")
        AX.AXUIElementSetAttributeValue(el, "AXFocused", True)
        if AX.AXUIElementSetAttributeValue(el, "AXValue", text) == 0 and _attr(el, "AXValue") == text:
            return f"已在 {desc} 填入文字（未按回车）"
        _mouse_click(*_center(info))
        _press_combo("cmd+a")
        _type(text)
        return f"已在 {desc} 键入文字（未按回车）"
    raise ToolError(f"不支持的 action：{action}")


# ---------------------------------------------------------------- 鼠标键盘（Quartz 事件）

KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13,
    "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25,
    "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37, "j": 38,
    "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47, "`": 50,
    "return": 36, "enter": 36, "tab": 48, "space": 49, "backspace": 51, "delete": 51, "escape": 53, "esc": 53,
    "forwarddelete": 117, "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101,
    "f10": 109, "f11": 103, "f12": 111,
}
MODS = {"cmd": Quartz.kCGEventFlagMaskCommand, "command": Quartz.kCGEventFlagMaskCommand,
        "super": Quartz.kCGEventFlagMaskCommand, "shift": Quartz.kCGEventFlagMaskShift,
        "ctrl": Quartz.kCGEventFlagMaskControl, "control": Quartz.kCGEventFlagMaskControl,
        "alt": Quartz.kCGEventFlagMaskAlternate, "option": Quartz.kCGEventFlagMaskAlternate,
        "opt": Quartz.kCGEventFlagMaskAlternate, "fn": Quartz.kCGEventFlagMaskSecondaryFn}


def _flags(mods):
    f = 0
    for m in mods:
        if m.lower() not in MODS:
            raise ToolError(f"不认识的修饰键：{m}")
        f |= MODS[m.lower()]
    return f


def _post(ev):
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _mouse_click(x, y, button="left", clicks=1, mods=()):
    down, up, btn = {
        "left": (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft),
        "right": (Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight),
        "middle": (Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp, Quartz.kCGMouseButtonCenter),
    }[button]
    flags = _flags(mods)
    with self_hidden([(x, y)]):
        _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (x, y), 0))
        time.sleep(0.05)
        for n in range(1, clicks + 1):
            for kind in (down, up):
                ev = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), btn)
                Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, n)
                if flags:
                    Quartz.CGEventSetFlags(ev, flags)
                _post(ev)
                time.sleep(0.02)
        time.sleep(0.25)


def _type(text):
    """借剪贴板粘贴输入：模拟按键会被中文输入法（拼音等）截住，粘贴则原样进入，中英文、换行都可靠。
    粘贴前保存剪贴板原有内容，粘贴后还原。"""
    from AppKit import NSPasteboard, NSPasteboardTypeString
    pb = NSPasteboard.generalPasteboard()
    saved = []
    for item in pb.pasteboardItems() or []:
        saved.append({t: item.dataForType_(t) for t in item.types() if item.dataForType_(t) is not None})
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)
    _press_combo("cmd+v")
    time.sleep(0.35)                     # 等目标程序读完剪贴板再还原
    pb.clearContents()
    if saved:
        from AppKit import NSPasteboardItem
        items = []
        for d in saved:
            it = NSPasteboardItem.alloc().init()
            for t, data in d.items():
                it.setData_forType_(data, t)
            items.append(it)
        pb.writeObjects_(items)


def _press_combo(combo, repeat=1):
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ToolError("keys 不能为空")
    *mods, key = parts
    if key not in KEYCODES:
        raise ToolError(f"不认识的按键：{key}")
    flags = _flags(mods)
    for _ in range(max(1, min(int(repeat), 100))):
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, KEYCODES[key], down)
            Quartz.CGEventSetFlags(ev, flags)
            _post(ev)
        time.sleep(0.03)
    time.sleep(0.15)


def _check_screen_point(x, y):
    sx, sy = to_screen(x, y)
    w, h = _screen_size()
    if not (0 <= sx <= w and 0 <= sy <= h):
        raise ToolError(f"坐标 ({x},{y}) 超出屏幕范围")
    return sx, sy


def t_click(x, y, button="left", clicks=1, modifiers=None):
    sx, sy = _check_screen_point(x, y)
    _mouse_click(sx, sy, button, int(clicks), modifiers or [])
    return f"已{'双' if clicks == 2 else ''}点击 ({x},{y})"


def t_drag(x1, y1, x2, y2):
    a, b = _check_screen_point(x1, y1), _check_screen_point(x2, y2)
    with self_hidden([a, b]):
        _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, a, Quartz.kCGMouseButtonLeft))
        for i in range(1, 11):
            p = (a[0] + (b[0] - a[0]) * i / 10, a[1] + (b[1] - a[1]) * i / 10)
            _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDragged, p, Quartz.kCGMouseButtonLeft))
            time.sleep(0.02)
        _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, b, Quartz.kCGMouseButtonLeft))
    return f"已从 ({x1},{y1}) 拖到 ({x2},{y2})"


def t_type_text(text):
    info = next((i for i in _ELEMENTS.values() if _attr(i["el"], "AXFocused")), None)
    if info and _attr(info["el"], "AXSubrole") == "AXSecureTextField":
        raise ToolError("焦点在密码框里，出于安全考虑不输入，请让用户自己输入。")
    _type(text)
    return f"已输入 {len(text)} 个字符（未按回车）"


def t_press_key(keys, repeat=1):
    _press_combo(keys, repeat)
    return f"已按 {keys}" + (f" ×{repeat}" if int(repeat) > 1 else "")


def t_scroll(x, y, direction="down", amount=3):
    sx, sy = _check_screen_point(x, y)
    n = max(1, min(int(amount), 50))
    dy = {"up": n, "down": -n}.get(direction, 0)
    dx = {"left": n, "right": -n}.get(direction, 0)
    with self_hidden([(sx, sy)]):
        _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (sx, sy), 0))
        _post(Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 2, dy, dx))
        time.sleep(0.3)
    return f"已在 ({x},{y}) 向{ {'up': '上', 'down': '下', 'left': '左', 'right': '右'}[direction] }滚动 {n} 格"


def t_wait(seconds=1.0):
    time.sleep(max(0.0, min(float(seconds), 30.0)))
    return f"已等待 {seconds} 秒"


# ---------------------------------------------------------------- 网页（在浏览器里直接跑 JavaScript，不截图、不动鼠标）

CHROMIUM = ["Comet", "Google Chrome", "Chromium", "Microsoft Edge", "Brave Browser", "Arc", "Vivaldi", "Opera"]
BROWSERS = CHROMIUM + ["Safari"]

# 给页面上可见的可交互元素编号（data-mcid），返回标题 / 网址 / 正文 / 元素清单 / 图片
_READ_JS = r"""
(() => {
  const opt = __OPT__;
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'; };
  const inView = el => { const r = el.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; };
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-mcid]').forEach(e => e.removeAttribute('data-mcid'));
  const sel = 'a[href],button,input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=tab],' +
              '[role=menuitem],[role=checkbox],[contenteditable=true],[onclick],summary,label[for]';
  const items = []; let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (!vis(el) || (opt.viewport && !inView(el))) continue;
    if (items.length >= opt.max) break;
    const id = ++n; el.setAttribute('data-mcid', id);
    const tag = el.tagName.toLowerCase();
    let kind = tag === 'a' ? '链接' : tag === 'button' || el.getAttribute('role') === 'button' ? '按钮'
             : tag === 'select' ? '下拉框' : tag === 'textarea' || el.isContentEditable ? '文本框'
             : tag === 'input' ? ({checkbox: '复选框', radio: '单选', submit: '按钮', button: '按钮', search: '搜索框'}[el.type] || '输入框')
             : (el.getAttribute('role') || tag);
    let label = clean(el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt') || '');
    if (!label && el.querySelector('img')) label = '[图片] ' + clean(el.querySelector('img').alt);
    const extra = [];
    if (el.placeholder) extra.push('提示=' + clean(el.placeholder).slice(0, 30));
    if (tag === 'input' || tag === 'textarea') { if (el.type === 'password') extra.push('密码框'); else if (el.value) extra.push('值=' + clean(el.value).slice(0, 40)); }
    if (el.checked) extra.push('已选中');
    if (el.disabled) extra.push('不可用');
    if (tag === 'a' && opt.links) extra.push(el.href.slice(0, 120));
    items.push(`[${id}] ${kind} "${label.slice(0, 60)}"` + (extra.length ? ' ' + extra.join(' ') : '') + (inView(el) ? '' : ' (需滚动)'));
  }
  const imgs = opt.images ? [...document.images].filter(i => i.naturalWidth >= 120 && vis(i))
      .slice(0, opt.images).map(i => `${i.naturalWidth}x${i.naturalHeight} ${clean(i.alt).slice(0, 30)} ${i.currentSrc || i.src}`) : [];
  const text = clean(document.body ? document.body.innerText : '');
  return JSON.stringify({title: document.title, url: location.href, scroll: [scrollY, document.documentElement.scrollHeight, innerHeight],
                         text: text.slice(opt.offset, opt.offset + opt.chars), textLen: text.length, items, imgs});
})()
"""

_ACT_JS = r"""
(() => {
  const a = __ARGS__;
  const el = a.id ? document.querySelector(`[data-mcid="${a.id}"]`) : null;
  if (a.id && !el) return 'ERR:找不到编号 ' + a.id + '（页面变了），请重新 web_read';
  if (a.action === 'click') { el.scrollIntoView({block: 'center'}); el.focus && el.focus(); el.click(); return 'OK'; }
  if (a.action === 'fill' || a.action === 'submit') {
    if (el.type === 'password') return 'ERR:不向密码框输入，请让用户自己输入';
    el.scrollIntoView({block: 'center'}); el.focus();
    if (el.isContentEditable) { el.textContent = a.text; }
    else { const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
           Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, a.text); }   // React 等框架也能感知
    el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true}));
    if (a.action === 'submit') {
      const opts = {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true};
      el.dispatchEvent(new KeyboardEvent('keydown', opts)); el.dispatchEvent(new KeyboardEvent('keypress', opts));
      el.dispatchEvent(new KeyboardEvent('keyup', opts));
      if (el.form) { el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit(); }
    }
    return 'OK';
  }
  if (a.action === 'scroll') { scrollBy(0, (a.text === 'up' ? -1 : 1) * innerHeight * 0.85); return 'OK'; }
  if (a.action === 'back') { history.back(); return 'OK'; }
  return 'ERR:不支持的 action';
})()
"""


def _pick_browser(app=None):
    if app:
        a = _find_running(app)
        if not a:
            raise ToolError(f"{app} 没有在运行，先用 open 打开它")
        return a["name"]
    front = frontmost_app()
    if front and front["name"] in BROWSERS:
        return front["name"]
    for name in BROWSERS:
        if _find_running(name):
            return name
    raise ToolError("没有正在运行的浏览器，先用 open 打开一个（比如 Comet）")


def _run_js(browser, js, timeout=30):
    if browser in CHROMIUM:
        line = f'tell application {_as_str(browser)} to execute active tab of front window javascript (item 1 of argv)'
    else:
        line = f'tell application {_as_str(browser)} to do JavaScript (item 1 of argv) in front document'
    p = subprocess.run(["osascript", "-e", "on run argv", "-e", line, "-e", "end run", js],
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        err = p.stderr.strip()
        if "JavaScript" in err and ("turned off" in err or "关闭" in err or "not allowed" in err or "Allow" in err):
            raise ToolError(f"{browser} 没开「允许 Apple 事件中的 JavaScript」：请用户在 {browser} 菜单栏 "
                            "View/显示 → Developer/开发者 里打开它。在那之前改用 read_ui / 截图。")
        raise ToolError(err or "执行网页脚本失败")
    return p.stdout.strip()


def t_web_read(app=None, max_items=150, text_chars=4000, text_offset=0, images=0, links=False, viewport_only=False):
    browser = _pick_browser(app)
    opt = {"max": int(max_items), "chars": int(text_chars), "offset": int(text_offset), "images": int(images),
           "links": bool(links), "viewport": bool(viewport_only)}
    raw = _run_js(browser, _READ_JS.replace("__OPT__", json.dumps(opt)))
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        raise ToolError(f"读取失败（页面可能还在加载）：{raw[:200]}")
    y, h, vh = d["scroll"]
    lines = [f"{browser} · {d['title']}", d["url"],
             f"滚动位置 {y}/{max(h - vh, 0)}px（页面高 {h}px，一屏 {vh}px）", "",
             f"—— 正文（第 {opt['offset']}–{opt['offset'] + len(d['text'])} 字，共 {d['textLen']} 字）——", d["text"]]
    if opt["offset"] + len(d["text"]) < d["textLen"]:
        lines.append(f"…（还有更多正文，用 text_offset={opt['offset'] + len(d['text'])} 继续读）")
    lines += ["", f"—— 可交互元素（{len(d['items'])} 个，用 web_act 按编号操作）——", *d["items"]]
    if d["imgs"]:
        lines += ["", "—— 图片（宽x高 说明 地址）——", *d["imgs"]]
    return "\n".join(lines)


def t_web_act(action, id=None, text=None, url=None, js=None, app=None):
    browser = _pick_browser(app)
    if action == "goto":
        if not url:
            raise ToolError("goto 需要 url")
        if browser in CHROMIUM:
            _osascript(f"tell application {_as_str(browser)} to set URL of active tab of front window to {_as_str(url)}")
        else:
            _osascript(f"tell application {_as_str(browser)} to set URL of front document to {_as_str(url)}")
        time.sleep(2)
        return f"已在 {browser} 打开 {url}（页面可能还在加载，需要时 wait 一下再 web_read）"
    if action == "js":
        if not js:
            raise ToolError("js 需要 js 参数")
        out = _run_js(browser, js)
        return out[:12000] if out else "（执行完毕，无返回值；需要结果请让脚本最后一个表达式返回字符串）"
    if action in ("click", "fill", "submit") and id is None:
        raise ToolError(f"{action} 需要 id（先 web_read 拿编号）")
    if action in ("fill", "submit") and text is None:
        raise ToolError(f"{action} 需要 text")
    args = {"action": action, "id": id, "text": text}
    out = _run_js(browser, _ACT_JS.replace("__ARGS__", json.dumps(args, ensure_ascii=False)))
    if out.startswith("ERR:"):
        raise ToolError(out[4:])
    time.sleep(1.0 if action in ("click", "submit", "back") else 0.4)
    try:
        now = json.loads(_run_js(browser, "JSON.stringify([document.title, location.href])"))
        after = f"；现在页面：{now[0]} {now[1]}"
    except Exception:  # noqa: BLE001 — 页面正在跳转时读不到，属正常
        after = "；页面正在跳转，稍后 web_read 查看"
    what = {"click": f"已点击 [{id}]", "fill": f"已在 [{id}] 填入文字（未提交）", "submit": f"已在 [{id}] 填入并提交",
            "scroll": f"已向{'上' if text == 'up' else '下'}滚动一屏", "back": "已后退"}[action]
    return what + after


# ---------------------------------------------------------------- 控制台窗口避让

def _self_windows():
    if not SELF_PID:
        return []
    out = []
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []:
        if w.get("kCGWindowOwnerPID") == SELF_PID:
            b = w["kCGWindowBounds"]
            out.append((b["X"], b["Y"], b["Width"], b["Height"]))
    return out


@contextmanager
def self_hidden(points=None):
    """临时隐藏控制台窗口（截图时总是隐藏；鼠标操作只在落点被它盖住时隐藏）。
    隐藏/恢复都不会抢走当前程序的焦点。"""
    wins = _self_windows()
    if points is not None:
        wins = [r for r in wins if any(r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3] for x, y in points)]
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(SELF_PID) if wins else None
    if app is None:
        yield
        return
    app.hide()
    for _ in range(25):
        if not _self_windows():
            break
        time.sleep(0.02)
    time.sleep(0.05)
    try:
        yield
    finally:
        app.unhide()


# ---------------------------------------------------------------- 工作文件夹与笔记（跨会话保留调研成果）

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


# ---------------------------------------------------------------- 截图

def t_screenshot(mark_elements=False):
    """返回 [("text", ...), ("image", b64, mime)]。"""
    if not Quartz.CGPreflightScreenCaptureAccess():
        Quartz.CGRequestScreenCaptureAccess()
        raise ToolError(permission_hint(["屏幕录制"]))
    from PIL import Image, ImageDraw
    path = Path(os.environ.get("TMPDIR", "/tmp")) / f"macctrl_{os.getpid()}.png"
    with self_hidden():          # 控制台窗口不进截图
        subprocess.run(["screencapture", "-x", "-m", "-t", "png", str(path)], check=True, timeout=20)
    img = Image.open(path).convert("RGB")
    path.unlink(missing_ok=True)
    w, h = _screen_size()
    img = img.resize((round(w * SCALE), round(h * SCALE)), Image.LANCZOS)
    if mark_elements and _ELEMENTS:
        d = ImageDraw.Draw(img)
        for eid, info in _ELEMENTS.items():
            f = info["frame"]
            if not f or info["role"] == "AXWindow":
                continue
            x0, y0 = to_model(f[0], f[1])
            x1, y1 = to_model(f[0] + f[2], f[1] + f[3])
            d.rectangle([x0, y0, x1, y1], outline=(255, 0, 80), width=1)
            d.rectangle([x0, y0 - 11, x0 + 7 * len(str(eid)) + 4, y0], fill=(255, 0, 80))
            d.text((x0 + 2, y0 - 11), str(eid), fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    note = f"截图 {img.width}×{img.height}，图上的像素坐标可直接用于 click/scroll。"
    if mark_elements:
        note += " 红框数字是上一次 read_ui 的元素编号。"
    return [("text", note), ("image", base64.b64encode(buf.getvalue()).decode(), "image/jpeg")]


# ---------------------------------------------------------------- 工具注册表

def _schema(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


XY = {"x": {"type": "integer"}, "y": {"type": "integer"}}

TOOLS = [
    ("list_apps", t_list_apps, "列出正在运行的程序和最前面的程序；include_installed=true 时同时列出已安装的程序。",
     _schema({"include_installed": {"type": "boolean"}})),
    ("open", t_open, "打开程序、文件、文件夹或网址。target 可以是程序名（如 \"备忘录\"、\"Safari\"）、路径或 URL；"
     "给 app 时用该程序打开 target。", _schema({"target": {"type": "string"}, "app": {"type": "string"}}, ["target"])),
    ("activate_app", t_activate_app, "把某个程序切到最前面（没运行则启动）。键盘输入前务必先切到目标程序。",
     _schema({"name": {"type": "string"}}, ["name"])),
    ("quit_app", t_quit_app, "退出一个程序。", _schema({"name": {"type": "string"}}, ["name"])),
    ("run_applescript", t_run_applescript,
     "运行 AppleScript 并返回结果。对支持脚本的程序（访达、Safari、音乐、备忘录、提醒事项、日历、邮件、信息、"
     "System Events 等）这是最快最稳的方式，优先使用。", _schema({"script": {"type": "string"}}, ["script"])),
    ("run_shell", t_run_shell, "运行 zsh 命令并返回输出（文件操作、下载、查询系统信息等）。当前目录是本对话的工作文件夹；"
     "耗时很长的批量任务请放到后台（nohup … &）并把进度写到工作文件夹里的日志。",
     _schema({"command": {"type": "string"}, "timeout": {"type": "integer"}}, ["command"])),
    ("web_read", t_web_read,
     "读取浏览器（默认最前面的，或指定 app，如 \"Comet\"）当前网页：标题、网址、正文文字，以及带编号的链接/按钮/输入框清单。"
     "操作网页时优先用它和 web_act，不需要截图，浏览器不在前台也能用。正文太长时用 text_offset 分段读；"
     "images=N 列出前 N 张图片的尺寸和地址（下载图片用）；links=true 附带链接地址；viewport_only=true 只看当前屏。",
     _schema({"app": {"type": "string"}, "max_items": {"type": "integer"}, "text_chars": {"type": "integer"},
              "text_offset": {"type": "integer"}, "images": {"type": "integer"}, "links": {"type": "boolean"},
              "viewport_only": {"type": "boolean"}})),
    ("web_act", t_web_act,
     "操作浏览器当前网页。action：click（按 web_read 的编号点击）、fill（往输入框填 text，不提交）、"
     "submit（填 text 并回车提交，用于搜索框）、scroll（text=\"up\" 向上，否则向下一屏）、goto（打开 url）、back（后退）、"
     "js（运行一段 JavaScript，返回最后一个表达式的值，用于批量提取数据）。页面变化后编号会失效，需重新 web_read。",
     _schema({"action": {"type": "string", "enum": ["click", "fill", "submit", "scroll", "goto", "back", "js"]},
              "id": {"type": "integer"}, "text": {"type": "string"}, "url": {"type": "string"},
              "js": {"type": "string"}, "app": {"type": "string"}}, ["action"])),
    ("read_ui", t_read_ui,
     "读取某个程序（默认最前面的程序）当前界面的辅助功能树，返回带编号的元素列表：[编号] 类型 \"名称\" 值 [状态] @(中心坐标)。"
     "之后用 ui_action 按编号操作。界面改变后编号失效，需重新读取。include_menu_bar=true 时附带菜单栏的全部菜单项。",
     _schema({"app": {"type": "string"}, "max_elements": {"type": "integer"},
              "include_menu_bar": {"type": "boolean"}})),
    ("ui_action", t_ui_action,
     "按 read_ui 的编号操作元素。action: press（按下按钮/菜单项/复选框等，首选）、click（鼠标点击中心）、"
     "show_menu（右键菜单）、focus（聚焦）、set_text（在输入框填入 text，会覆盖原内容，不会按回车）。",
     _schema({"id": {"type": "integer"},
              "action": {"type": "string", "enum": ["press", "click", "show_menu", "focus", "set_text"]},
              "text": {"type": "string"}}, ["id"])),
    ("screenshot", t_screenshot,
     "截取主屏幕。读不到界面元素、或需要看图片/画面内容时使用。mark_elements=true 会把上次 read_ui 的编号画在图上。",
     _schema({"mark_elements": {"type": "boolean"}})),
    ("click", t_click, "在截图坐标 (x,y) 处点击。button: left/right/middle；clicks: 1 或 2（双击）；"
     "modifiers 如 [\"cmd\"]。", _schema({**XY, "button": {"type": "string", "enum": ["left", "right", "middle"]},
                                            "clicks": {"type": "integer"},
                                            "modifiers": {"type": "array", "items": {"type": "string"}}}, ["x", "y"])),
    ("drag", t_drag, "按住左键从 (x1,y1) 拖到 (x2,y2)。",
     _schema({k: {"type": "integer"} for k in ("x1", "y1", "x2", "y2")}, ["x1", "y1", "x2", "y2"])),
    ("type_text", t_type_text, "在当前焦点处输入文字（通过粘贴输入，不受中文输入法影响，支持中文和换行）。不会按回车。"
     "需要提交时再单独调用 press_key(\"return\")。", _schema({"text": {"type": "string"}}, ["text"])),
    ("press_key", t_press_key, "按键或组合键，如 \"return\"、\"esc\"、\"cmd+c\"、\"cmd+shift+4\"、\"down\"。",
     _schema({"keys": {"type": "string"}, "repeat": {"type": "integer"}}, ["keys"])),
    ("scroll", t_scroll, "在 (x,y) 处滚动。direction: up/down/left/right；amount 为行数。",
     _schema({**XY, "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
              "amount": {"type": "integer"}}, ["x", "y", "direction"])),
    ("note_write", t_note_write,
     "把调研结论、要点、来源链接、待办写进本对话工作文件夹里的笔记（Markdown）。默认追加；append=false 为整篇覆盖"
     "（用于整理最终版）。关闭程序后也会保留，下次继续时可以读回来。",
     _schema({"name": {"type": "string", "description": "笔记文件名，如 \"调研笔记\"、\"总结\""},
              "content": {"type": "string"}, "append": {"type": "boolean"}}, ["name", "content"])),
    ("note_read", t_note_read, "读取本对话工作文件夹里的一篇笔记或文本文件。",
     _schema({"name": {"type": "string"}, "max_chars": {"type": "integer"}}, ["name"])),
    ("note_list", t_note_list, "列出本对话工作文件夹里的笔记和文件（含下载的文件）。继续之前的任务时先看一下。",
     _schema({})),
    ("wait", t_wait, "等待若干秒（等页面/程序加载）。", _schema({"seconds": {"type": "number"}}, ["seconds"])),
]
TOOL_MAP = {name: fn for name, fn, _, _ in TOOLS}


SCREEN_TOOLS = {"read_ui", "ui_action", "screenshot", "click", "drag", "type_text", "press_key", "scroll",
                "activate_app"}


def screen_locked():
    return bool((Quartz.CGSessionCopyCurrentDictionary() or {}).get("CGSSessionScreenIsLocked"))


def run_tool(name, args):
    """执行工具，返回 (parts, is_error)。parts 是 [("text", s) | ("image", b64, mime)]。"""
    fn = TOOL_MAP.get(name)
    if fn is None:
        return [("text", f"未知工具：{name}")], True
    if name in SCREEN_TOOLS and screen_locked():   # 锁屏时截图全黑、点击无效，别在黑屏上乱操作
        return [("text", "屏幕已锁定：界面类操作（截图、点击、输入、读界面）现在都做不了。"
                         "请停下来告诉用户先解锁 Mac，解锁后再继续；不需要界面的操作（命令、脚本、笔记）仍可进行。")], True
    try:
        out = fn(**(args or {}))
        return (out if isinstance(out, list) else [("text", str(out))]), False
    except ToolError as e:
        return [("text", str(e))], True
    except subprocess.TimeoutExpired:
        return [("text", "执行超时")], True
    except Exception as e:  # noqa: BLE001 — 工具错误要回给模型，而不是让整个循环崩掉
        return [("text", f"{type(e).__name__}: {e}")], True


if __name__ == "__main__":   # 调试：python mac_tools.py read_ui '{"app": "访达"}'
    import sys
    parts, err = run_tool(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {})
    for p in parts:
        print(p[1] if p[0] == "text" else f"<image {len(p[1])} b64>")
    sys.exit(1 if err else 0)
