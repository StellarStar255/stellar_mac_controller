"""Mac 控制台：用一句话让助手操作这台 Mac 上的程序。运行：python3 app.py（PyQt6）"""
import html
import json
import os
import shutil
import tempfile
import re
import subprocess
import sys
import time
from pathlib import Path

import PyQt6
if sys.platform == "darwin":
    import ApplicationServices as AX

# Anaconda 自带的 qt.conf 会把插件路径指到它自己的 Qt，这里强制用 PyQt6 自带的插件
os.environ["QT_PLUGIN_PATH"] = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "plugins")

from PyQt6.QtCore import QSettings, Qt, QTimer, QUrl, QLocale  # noqa: E402
from PyQt6.QtGui import (QDesktopServices, QFont, QIcon, QImage, QKeyEvent, QKeySequence, QPixmap, QShortcut,
                         QTextDocument)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                             QInputDialog,
                             QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                             QVBoxLayout, QWidget)

import chat_store
import platform_tools as mac_tools
import i18n
from i18n import tr
from version import __version__
from backends import ApiBackend, Bridge, ClaudeCodeBackend, CodexBackend, codex_models, codex_reasoning_levels

HERE = Path(__file__).resolve().parent
ASSET_DIR = (Path(tempfile.gettempdir()) / "stellar-mac-controller-icons"
             if getattr(sys, "frozen", False) else HERE / "assets")
BACKENDS = {"本机 Claude Code": ["（默认）", "opus", "sonnet", "haiku"],
            "本机 Codex": ["（默认）"],
            "Claude API": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]}
EXAMPLES = ["打开备忘录，新建一条笔记写上今天的待办",
            "在小红书上调研一个话题，把要点整理成报告",
            "把下载文件夹里的 PDF 移到桌面的「资料」文件夹",
            "音乐暂停，音量调到 30%"]
PANES = {"辅助功能": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
         "屏幕录制": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"}
if sys.platform != "darwin":
    PANES = {}
MINI_W, MINI_H = 360, 52
COMPACT_SHORTCUT = "Ctrl+Shift+M"  # Qt maps Ctrl to Command on macOS.


def app_settings():
    if os.environ.get("MACCTRL_GUI_SMOKE"):
        return QSettings(str(Path(os.environ["MAC_CTRL_DATA_DIR"]) / "settings.ini"), QSettings.Format.IniFormat)
    return QSettings("Stellar", "MacController")

TOOL_CN = {
    "list_apps": ("🗂", "查看程序"), "open": ("🚀", "打开"), "activate_app": ("🔀", "切换到"),
    "quit_app": ("⏻", "退出程序"), "run_applescript": ("📜", "运行脚本"), "run_shell": ("⌨️", "运行命令"),
    "read_ui": ("🔍", "读取界面"), "ui_action": ("👆", "操作元素"), "screenshot": ("📸", "截图"),
    "click": ("🖱", "点击"), "drag": ("🖱", "拖动"), "type_text": ("⌨️", "输入文字"), "press_key": ("⌨️", "按键"),
    "scroll": ("🖱", "滚动"), "wait": ("⏳", "等待"), "note_write": ("📝", "写笔记"), "note_read": ("📖", "读笔记"),
    "note_list": ("📂", "查看文件"), "read_file": ("📄", "查看附件"),
    "web_read": ("🌐", "读网页"), "web_act": ("🌐", "操作网页"),
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp", ".tiff"}

# ---------------------------------------------------------------- 主题（跟随系统深色 / 浅色）

THEMES = {
    "dark": dict(bg="#18191c", surface="#222327", surface2="#2b2d32", border="#34363c", text="#ececef",
                 muted="#8e9097", accent="#4f7cff", accent_hover="#6690ff", accent_text="#ffffff",
                 danger="#e5534b", warn_bg="#3a3120", warn_text="#f0c56b"),
    "light": dict(bg="#f4f4f6", surface="#ffffff", surface2="#eeeef2", border="#dedee4", text="#1d1d1f",
                  muted="#6e6e76", accent="#2f6fed", accent_hover="#4a82f0", accent_text="#ffffff",
                  danger="#d93b32", warn_bg="#fff3d6", warn_text="#7a5500"),
}


ICON_PATHS = {   # 24×24 线条图标
    "chevron": "M7 10l5 5 5-5",
    "plus": "M12 5v14M5 12h14",
    "folder": "M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z",
    "sliders": "M4 7h9M17 7h3M4 17h3M11 17h9M15 5v4M9 15v4",
    "clip": "M20 11.5l-7.8 7.8a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8",
}


def svg_icon(name, color):
    path = ASSET_DIR / f"{name}_{color.lstrip('#')}.svg"
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
                        f'<path d="{ICON_PATHS[name]}" fill="none" stroke="{color}" stroke-width="1.8" '
                        f'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return path.as_posix()


def stylesheet(t):
    return f"""
    QMainWindow, QWidget#root {{ background: {t['bg']}; }}
    QWidget {{ color: {t['text']}; font-size: 13px; }}
    QLabel#muted, QLabel#status {{ color: {t['muted']}; font-size: 12px; }}
    QLabel#title {{ font-size: 20px; font-weight: 600; }}

    QPushButton {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 8px;
                   padding: 5px 12px; }}
    QPushButton:hover {{ background: {t['border']}; }}
    QPushButton#icon {{ min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0;
                        font-size: 15px; border-radius: 8px; }}
    QPushButton#icon:checked {{ background: {t['accent']}; border-color: {t['accent']}; color: {t['accent_text']}; }}
    QPushButton#send {{ background: {t['accent']}; border: none; color: {t['accent_text']}; font-size: 16px;
                        font-weight: 700; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
                        border-radius: 16px; padding: 0; }}
    QPushButton#send:hover {{ background: {t['accent_hover']}; }}
    QPushButton#send[running="true"] {{ background: {t['danger']}; font-size: 12px; }}
    QPushButton#chip {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px;
                        padding: 9px 14px; text-align: left; color: {t['text']}; }}
    QPushButton#chip:hover {{ border-color: {t['accent']}; }}
    QPushButton#link {{ background: transparent; border: none; color: {t['muted']}; padding: 2px 4px;
                        font-size: 12px; }}
    QPushButton#link:hover {{ color: {t['accent']}; }}

    QComboBox {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 8px;
                 padding: 5px 28px 5px 10px; min-height: 20px; }}
    QComboBox:hover {{ border-color: {t['muted']}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url({svg_icon('chevron', t['muted'])}); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']};
                                   selection-background-color: {t['accent']}; selection-color: {t['accent_text']};
                                   padding: 4px; outline: none; }}
    QComboBox QLineEdit {{ background: transparent; border: none; }}

    QFrame#card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
    QFrame#composer {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px; }}
    QFrame#composer[focus="true"] {{ border-color: {t['accent']}; }}
    QPlainTextEdit#input {{ background: transparent; border: none; font-size: 14px;
                            selection-background-color: {t['accent']}; }}
    QFrame#warn {{ background: {t['warn_bg']}; border-radius: 10px; }}
    QFrame#warn QLabel {{ color: {t['warn_text']}; font-size: 12px; }}
    QFrame#warn QPushButton {{ background: transparent; border: 1px solid {t['warn_text']}; color: {t['warn_text']};
                               border-radius: 7px; padding: 3px 10px; font-size: 12px; }}
    QFrame#mini {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}

    QScrollArea, QScrollArea > QWidget > QWidget#chat {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

    QLabel#user {{ background: {t['accent']}; color: {t['accent_text']}; border-radius: 14px; padding: 8px 12px;
                   font-size: 14px; }}
    QLabel#bot {{ font-size: 14px; }}
    QLabel#meta {{ color: {t['muted']}; font-size: 11px; }}
    QLabel#metaerr {{ color: {t['danger']}; font-size: 12px; }}
    QFrame#steps {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    QFrame#steps QLabel {{ color: {t['muted']}; font-size: 12px; }}
    QPushButton#stepsHead {{ background: transparent; border: none; color: {t['muted']}; text-align: left;
                             padding: 0; font-size: 12px; }}
    QPushButton#stepsHead:hover {{ color: {t['text']}; }}
    QCheckBox {{ spacing: 6px; }}
    QPushButton#clip {{ background: transparent; border: none; min-width: 26px; max-width: 26px; min-height: 30px;
                        padding: 0; }}
    QPushButton#clip:hover {{ background: {t['surface2']}; border-radius: 8px; }}
    QFrame#att {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 9px; }}
    QFrame#att QLabel {{ font-size: 12px; }}
    QPushButton#attx {{ background: transparent; border: none; color: {t['muted']}; padding: 0 4px; font-size: 13px; }}
    QPushButton#attx:hover {{ color: {t['danger']}; }}
    QPushButton#fileChip {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px;
                            padding: 7px 12px; font-size: 12px; }}
    QPushButton#fileChip:hover {{ border-color: {t['accent']}; }}
    QLabel#thumb {{ border: 1px solid {t['border']}; border-radius: 10px; }}
    QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 6px; }}
    """


# ---------------------------------------------------------------- 文本处理

def tool_line(text):
    """把「工具名 {参数JSON}」变成一行简短的中文说明。"""
    name, _, args = text.partition(" ")
    icon, label = TOOL_CN.get(name, ("▸", name))
    if name in ("click", "scroll"):
        xy = re.findall(r'"[xy]":\s*(-?\d+)', args)
        detail = f"({', '.join(xy)})" if xy else ""
    else:
        m = re.search(r'"\w+":\s*"((?:[^"\\]|\\.)*)', args) or re.search(r'"\w+":\s*([^,}]+)', args)
        detail = m.group(1) if m else ""
    detail = re.sub(r"\\[nt]|\s+", " ", detail).replace('\\"', '"').strip()
    if name == "read_file":
        detail = Path(detail).name
    if name == "web_act":
        act = re.search(r'"action":\s*"(\w+)"', args)
        target = re.search(r'"(?:url|text)":\s*"((?:[^"\\]|\\.)*)', args) or re.search(r'"id":\s*(\d+)', args)
        names = {"click": "点击", "fill": "填写", "submit": "提交", "scroll": "滚动", "goto": "打开", "back": "后退", "js": "运行脚本"}
        detail = tr(names.get(act.group(1), act.group(1))) + (f" {target.group(1)[:50]}" if act and target else "") if act else detail
    if name == "web_read":
        detail = ""
    if len(detail) > 60:
        detail = detail[:60] + "…"
    return f"{icon}  {tr(label)}" + (f" · {detail}" if detail else "")


def pretty_model(model_id):
    """claude-opus-5-5[1m] → Opus 5.5（1M 上下文）"""
    m = re.match(r"claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?(\[1m\])?$", model_id or "")
    if not m:
        return model_id or ""
    name = m.group(1).capitalize() + " " + m.group(2) + (f".{m.group(3)}" if m.group(3) else "")
    return name + (tr("（1M 上下文）") if m.group(4) else "")


def md_to_html(text):
    """Markdown → HTML（Qt 自带解析），再补上行距和段距；单个换行按原样保留。"""
    out, in_code = [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append(line)
        else:
            out.append(line if in_code or not line.strip() else line + "  ")
    doc = QTextDocument()
    doc.setMarkdown("\n".join(out))
    body = doc.toHtml()
    body = body[body.find("<body"):]
    body = re.sub(r"<p style=\"", '<p style="line-height:150%; margin-top:0; margin-bottom:8px; ', body)
    body = re.sub(r"<li style=\"", '<li style="line-height:150%; margin-bottom:3px; ', body)
    body = re.sub(r"-qt-list-indent: 1;", "-qt-list-indent: 1; margin-left:-18px;", body)
    return body


# ---------------------------------------------------------------- 对话区

class ClickLabel(QLabel):
    """可点击的图片。注意：Qt 的事件函数不能有返回值，否则 PyQt6 会直接终止整个程序。"""

    def __init__(self, on_click):
        super().__init__()
        self.on_click = on_click

    def mousePressEvent(self, e):
        self.on_click()


class StepsCard(QFrame):
    """连续的工具步骤合成一张卡片：默认只显示步数和最新一步，点开看全部。"""

    def __init__(self, danger):
        super().__init__()
        self.setObjectName("steps")
        self.danger = danger
        self.lines = []
        self.expanded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(3)
        self.head = QPushButton()
        self.head.setObjectName("stepsHead")
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        self.head.clicked.connect(self.toggle)
        lay.addWidget(self.head)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.body)

    def add(self, kind, text):
        self.lines.append((kind, tool_line(text) if kind == "tool" else f"✗ {tr(text)}"))
        self.refresh()

    def toggle(self):
        self.expanded = not self.expanded
        self.refresh()

    def refresh(self):
        n = sum(1 for k, _ in self.lines if k == "tool")
        errs = sum(1 for k, _ in self.lines if k == "err")
        arrow = "▾" if self.expanded else "▸"
        self.head.setText(f"{arrow}  " + tr("执行了 {n} 步", n=n) +
                          (tr("，{n} 次出错", n=errs) if errs else "") +
                          ("" if self.expanded or n < 2 else tr("　点开查看")))
        shown = self.lines if self.expanded else self.lines[-1:]

        def fmt(k, t):
            color = f' style="color:{self.danger}"' if k == "err" else ""
            return f"<div{color}>{html.escape(t)}</div>"
        self.body.setText("".join(fmt(k, t) for k, t in shown))


class ChatView(QScrollArea):
    def __init__(self, on_example, theme):
        super().__init__()
        self.theme = theme
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.inner.setObjectName("chat")
        self.lay = QVBoxLayout(self.inner)
        self.lay.setContentsMargins(6, 8, 10, 8)
        self.lay.setSpacing(12)
        self.lay.addStretch(1)
        self.setWidget(self.inner)
        self.on_example = on_example
        self.bubbles = []
        self.steps = None
        self.stick = True
        bar = self.verticalScrollBar()
        # 内容高度变了就贴底，直到用户自己往上翻
        bar.rangeChanged.connect(lambda _lo, hi: bar.setValue(hi) if self.stick else None)
        bar.valueChanged.connect(lambda v: setattr(self, "stick", v >= bar.maximum() - 8))

    def clear(self):
        while self.lay.count() > 1:
            item = self.lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.bubbles, self.steps, self.stick = [], None, True

    def _insert(self, w, align=None):
        if align is None:
            self.lay.insertWidget(self.lay.count() - 1, w)
        else:
            self.lay.insertWidget(self.lay.count() - 1, w, 0, align)

    def show_empty(self):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(4, 30, 4, 0)
        v.setSpacing(10)
        title = QLabel(tr("想让 Mac 做什么？" if sys.platform == "darwin" else "想让电脑做什么？"))
        title.setObjectName("title")
        v.addWidget(title)
        sub = QLabel(tr("用一句话告诉我，我会直接操作这台电脑上的程序。对话、笔记和下载的文件都会自动保存，下次可以接着做。"))
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        v.addWidget(sub)
        v.addSpacing(8)
        for ex in EXAMPLES:
            b = QPushButton(tr(ex))
            b.setObjectName("chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, t=tr(ex): self.on_example(t))
            v.addWidget(b)
        self._insert(box)

    def add(self, kind, text):
        if kind in ("tool", "err") and self.steps is not None:
            self.steps.add(kind, text)
            return
        if kind == "tool":
            self.steps = StepsCard(self.theme["danger"])
            self.steps.add(kind, text)
            self._insert(self.steps)
            return
        self.steps = None
        if kind == "files":
            self._insert(self._files_row([Path(p) for p in json.loads(text)]), Qt.AlignmentFlag.AlignRight)
            return
        if kind == "user":
            lab = QLabel(html.escape(text).replace("\n", "<br>"))
            lab.setObjectName("user")
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lab.setMaximumWidth(self._bubble_max())
            self.bubbles.append(lab)
            # 放进「弹簧 + 气泡」的横排里靠右：直接用 AlignRight 时 Qt 会把换行后的高度算小，文字被截断
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addStretch(1)
            h.addWidget(lab)
            self._insert(row)
        elif kind == "bot":
            lab = QLabel()
            lab.setObjectName("bot")
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setText(md_to_html(text))
            lab.setWordWrap(True)
            lab.setOpenExternalLinks(True)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            self._insert(lab)
        else:
            lab = QLabel(tr(text))
            lab.setObjectName("metaerr" if kind in ("meta_err", "err") else "meta")
            lab.setWordWrap(True)
            self._insert(lab)

    def _files_row(self, paths):
        """发出去的附件：图片显示缩略图，其它文件显示成可点开的小卡片。"""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for p in paths:
            thumb = file_thumb(p, 150)
            if thumb:
                w = ClickLabel(lambda q=p: QDesktopServices.openUrl(QUrl.fromLocalFile(str(q))))
                w.setObjectName("thumb")
                w.setPixmap(thumb)
                w.setCursor(Qt.CursorShape.PointingHandCursor)
                w.setToolTip(tr(f"{p.name}（点击打开）"))
            else:
                w = QPushButton(f"{file_icon(p)}  {p.name}")
                w.setObjectName("fileChip")
                w.setCursor(Qt.CursorShape.PointingHandCursor)
                w.setToolTip(str(p))
                w.clicked.connect(lambda _, q=p: QDesktopServices.openUrl(QUrl.fromLocalFile(str(q))))
            lay.addWidget(w)
        return box

    def _bubble_max(self):
        return max(200, int(self.viewport().width() * 0.8))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        for b in self.bubbles:
            b.setMaximumWidth(self._bubble_max())


def local_files(mime):
    return [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile() and Path(u.toLocalFile()).is_file()]


class _Input(QPlainTextEdit):
    def __init__(self, on_send, composer):
        super().__init__()
        self.on_send, self.composer = on_send, composer

    def canInsertFromMimeData(self, source):
        return bool(local_files(source)) or source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        """⌘V / 拖入：文件（访达里复制的）→ 附件；图片（截图）→ 存成 PNG 附件；其它照常粘贴文字。"""
        files = local_files(source)
        if files:
            self.composer.add_files(files)
        elif source.hasImage():
            img = QImage(source.imageData())
            if not img.isNull():
                path = Path(tempfile.mkdtemp(prefix="macctrl_")) / f"粘贴的图片 {time.strftime('%H%M%S')}.png"
                img.save(str(path), "PNG")
                self.composer.add_files([path])
        else:
            super().insertFromMimeData(source)

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.on_send()
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.composer.set_focus_style(True)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.composer.set_focus_style(False)


def file_thumb(path, size):
    """图片返回缩略图，其它文件返回 None。"""
    if path.suffix.lower() not in IMAGE_EXTS:
        return None
    pm = QPixmap(str(path))
    if pm.isNull():
        return None
    return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def file_icon(path):
    ext = path.suffix.lower()
    return "🖼" if ext in IMAGE_EXTS else "📕" if ext == ".pdf" else "📄"


class AttachChip(QFrame):
    """输入框上方的附件卡片：缩略图 + 文件名 + ✕"""

    def __init__(self, path, on_remove):
        super().__init__()
        self.setObjectName("att")
        self.path = path
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 2, 4)
        lay.setSpacing(6)
        pic = QLabel()
        thumb = file_thumb(path, 30)
        if thumb:
            pic.setPixmap(thumb)
        else:
            pic.setText(file_icon(path))
            pic.setStyleSheet("font-size:18px;")
        pic.setFixedSize(30, 30)
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(pic)
        name = path.name if len(path.name) <= 18 else path.name[:10] + "…" + path.name[-7:]
        lab = QLabel(name)
        lab.setToolTip(str(path))
        lay.addWidget(lab)
        x = QPushButton("✕")
        x.setObjectName("attx")
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setToolTip(tr("移除"))
        x.clicked.connect(lambda: on_remove(self))
        lay.addWidget(x)


class Composer(QFrame):
    """圆角输入卡片：附件栏 + 回形针 + 自动长高的输入框 + 圆形发送/停止按钮。
    Enter 发送，Shift+Enter 换行；⌘V 可粘贴截图/文件，也可以把文件拖进来。"""

    def __init__(self, on_send, icon_color):
        super().__init__()
        self.setObjectName("composer")
        self.files = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        self.att_bar = QWidget()
        self.att_lay = QHBoxLayout(self.att_bar)
        self.att_lay.setContentsMargins(2, 0, 2, 0)
        self.att_lay.setSpacing(6)
        self.att_lay.addStretch(1)
        self.att_bar.hide()
        outer.addWidget(self.att_bar)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.clip = QPushButton()
        self.clip.setObjectName("clip")
        self.clip.setToolTip(tr("添加图片、PDF 或其它文件（也可以直接粘贴或拖进来）"))
        self.clip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clip.clicked.connect(self.pick_files)
        self.set_icon_color(icon_color)
        row.addWidget(self.clip, 0, Qt.AlignmentFlag.AlignBottom)
        self.edit = _Input(on_send, self)
        self.edit.setObjectName("input")
        self.edit.setPlaceholderText(tr("描述你想做的事，可粘贴图片 / PDF…（Enter 发送）"))
        self.edit.document().contentsChanged.connect(self.fit)
        self.edit.textChanged.connect(self.refresh_button)
        row.addWidget(self.edit, 1)
        self.btn = QPushButton("↑")
        self.btn.setObjectName("send")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setToolTip(tr("发送"))
        row.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignBottom)
        outer.addLayout(row)
        self.fit()

    def set_icon_color(self, color):
        self.clip.setIcon(QIcon(svg_icon("clip", color)))

    def pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("添加文件"), str(Path.home() / "Downloads"),
                                                tr("常用文件 (*.png *.jpg *.jpeg *.gif *.webp *.heic *.pdf *.txt *.md "
                                                "*.csv *.docx *.xlsx *.pptx);;所有文件 (*)"))
        self.add_files([Path(p) for p in paths])

    def add_files(self, paths):
        for p in paths:
            if p.suffix.lower() == ".heic" and sys.platform == "darwin":
                out = Path(tempfile.mkdtemp(prefix="macctrl_")) / (p.stem + ".jpg")
                if subprocess.run(["sips", "-s", "format", "jpeg", str(p), "--out", str(out)],
                                  capture_output=True).returncode == 0:
                    p = out
            if p in self.files:
                continue
            self.files.append(p)
            self.att_lay.insertWidget(self.att_lay.count() - 1, AttachChip(p, self.remove_chip))
        self.att_bar.setVisible(bool(self.files))
        self.refresh_button()
        self.edit.setFocus()

    def remove_chip(self, chip):
        self.files.remove(chip.path)
        chip.deleteLater()
        self.att_bar.setVisible(bool(self.files))

    def take_files(self):
        files = list(self.files)
        self.files.clear()
        while self.att_lay.count() > 1:
            item = self.att_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.att_bar.hide()
        return files

    def fit(self):
        lines = max(1, min(6, int(self.edit.document().size().height())))
        self.edit.setFixedHeight(lines * self.edit.fontMetrics().lineSpacing() + 12)

    def _repolish(self, w):
        w.style().unpolish(w)
        w.style().polish(w)

    def set_running(self, on):
        self.running = on
        self.edit.setPlaceholderText(tr("继续输入，会在当前步骤结束后送达…（Enter 发送）" if on else
                                     "描述你想做的事，可粘贴图片 / PDF…（Enter 发送）"))
        self.refresh_button()

    def has_content(self):
        return bool(self.edit.toPlainText().strip() or self.files)

    def refresh_button(self):
        """执行中：框里有内容 → 发送（排队送达），没内容 → 停止。"""
        stop = getattr(self, "running", False) and not self.has_content()
        self.btn.setText("■" if stop else "↑")
        self.btn.setToolTip(tr("停止" if stop else "发送"))
        self.btn.setProperty("running", "true" if stop else "false")
        self._repolish(self.btn)

    def set_focus_style(self, on):
        self.setProperty("focus", "true" if on else "false")
        self._repolish(self)


def icon_button(text, tip):
    b = QPushButton(text)
    b.setObjectName("icon")
    b.setToolTip(tr(tip))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


# ---------------------------------------------------------------- 主窗口

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("Mac 控制台"))
        self.setAcceptDrops(True)
        self.resize(540, 780)
        self.setMinimumWidth(420)
        self.settings = app_settings()
        # Previous releases enabled pinning by default. Reset that old default
        # once; later explicit user choices remain persistent.
        if not self.settings.value("window_behavior_v2", False, type=bool):
            self.settings.setValue("pin", False)
            self.settings.setValue("window_behavior_v2", True)
        self.bridge = Bridge()
        self.backend = None
        self.backend_key = None
        self.running = False
        self.mini = False
        self.full_geom = None
        self.last_front = None          # 用户最近在用的其它程序（名字, pid）
        self.chat = None
        self.chats = []
        self.shown = []                 # 当前显示的条目（含不存盘的提示）
        dark = QApplication.instance().styleHints().colorScheme() != Qt.ColorScheme.Light
        self.theme = THEMES["dark" if dark else "light"]

        # 顶栏：对话 + 图标按钮
        self.history_box = QComboBox()
        self.history_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.history_box.setMinimumContentsLength(10)
        self.history_box.activated.connect(self.on_history)
        new_btn = icon_button("", tr("新对话"))
        new_btn.clicked.connect(self.new_chat)
        folder_btn = icon_button("", tr("打开本对话的文件夹（笔记、下载的文件都在这里）"))
        folder_btn.clicked.connect(self.open_folder)
        self.gear_btn = icon_button("", tr("设置：大脑、模型、选项"))
        self.icon_btns = {"plus": new_btn, "folder": folder_btn, "sliders": self.gear_btn}
        self.gear_btn.setCheckable(True)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(self.history_box, 1)
        top.addWidget(new_btn)
        top.addWidget(folder_btn)
        top.addWidget(self.gear_btn)

        # 设置面板（默认收起）
        self.settings_card = QFrame()
        self.settings_card.setObjectName("card")
        g = QGridLayout(self.settings_card)
        g.setContentsMargins(14, 12, 14, 12)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        self.backend_box = QComboBox()
        for name in BACKENDS:
            self.backend_box.addItem(tr(name), name)
        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        self.model_box.setToolTip(tr("选择模型，或直接输入模型 ID；每个后端分别记住选择"))
        self.effort_box = QComboBox()
        self.effort_box.setToolTip(tr("推理档位影响思考深度；模型会在所选档位内按需思考。low 偏快，medium 平衡，high 偏深入。默认沿用 Codex 配置；应用不自动切档。"))
        self.effort_label = QLabel(tr("推理强度"))
        self.effort_label.setObjectName("muted")
        g.addWidget(self.effort_label, 2, 0)
        g.addWidget(self.effort_box, 2, 1, 1, 2)
        key_btn = QPushButton("API Key")
        key_btn.clicked.connect(self.set_api_key)
        for i, (label, w) in enumerate((("大脑", self.backend_box), ("模型", self.model_box))):
            lab = QLabel(tr(label))
            lab.setObjectName("muted")
            g.addWidget(lab, i, 0)
            g.addWidget(w, i, 1)
        g.addWidget(key_btn, 0, 2)
        self.model_note = QLabel()
        self.model_note.setObjectName("muted")
        g.addWidget(self.model_note, 3, 1, 1, 2)
        g.setColumnStretch(1, 1)
        self.confirm_box = QCheckBox(tr("危险操作前确认"))
        self.confirm_box.setToolTip(tr("在管理员权限、发送消息、退出程序、关机等有风险的操作前弹窗确认；"
                                    "打开、查看、下载等直接执行"))
        self.delete_confirm_box = QCheckBox(tr("删除文件前确认"))
        self.delete_confirm_box.setToolTip(tr("勾选后，命令或脚本删除内容前也会弹窗；需同时开启危险操作确认。清空废纸篓仍按危险操作确认"))
        self.refocus_box = QCheckBox(tr("发送后切回原程序"))
        self.refocus_box.setToolTip(tr("发送后自动切回你刚才在用的程序，方便它直接操作"))
        self.mini_box = QCheckBox(tr("执行时收成小条"))
        self.mini_box.setToolTip(tr("任务执行期间窗口缩到屏幕右下角，不挡住要操作的页面；做完自动恢复"))
        self.pin_box = QCheckBox(tr("窗口置顶"))
        self.global_shortcut_box = QCheckBox(tr("全局快捷键 ⌘⇧M"))
        self.global_shortcut_box.setChecked(self.settings.value("global_compact_shortcut", True, type=bool))
        self.global_shortcut_box.setVisible(sys.platform == 'darwin')
        self.global_shortcut_box.toggled.connect(self.change_global_shortcut)
        opts = QGridLayout()
        opts.setHorizontalSpacing(18)
        opts.setVerticalSpacing(6)
        for i, w in enumerate((self.confirm_box, self.delete_confirm_box, self.refocus_box, self.mini_box, self.pin_box)):
            opts.addWidget(w, i // 2, i % 2)
        opts.addWidget(self.global_shortcut_box, 2, 1)
        g.addLayout(opts, 4, 0, 1, 3)
        from update_ui import UpdateController
        self.updater = UpdateController(self)
        update_btn = QPushButton(tr(f"检查更新 · v{__version__}"))
        update_btn.clicked.connect(self.updater.check)
        self.updater.button = update_btn
        g.addWidget(update_btn, 5, 0, 1, 3)
        self.language_box = QComboBox()
        self.language_box.addItem("English", "en")
        self.language_box.addItem("简体中文", "zh_CN")
        self.language_box.setCurrentIndex(max(0, self.language_box.findData(i18n.language())))
        g.addWidget(QLabel(tr("语言")), 6, 0)
        g.addWidget(self.language_box, 6, 1, 1, 2)
        self.language_box.currentIndexChanged.connect(self.change_language)
        self.settings_card.hide()
        self.gear_btn.toggled.connect(self.settings_card.setVisible)

        # 权限提示条
        self.perm_bar = QFrame()
        self.perm_bar.setObjectName("warn")
        pl = QHBoxLayout(self.perm_bar)
        pl.setContentsMargins(12, 7, 8, 7)
        self.perm_label = QLabel()
        pl.addWidget(self.perm_label, 1)
        self.perm_btns = {}
        for name, url in PANES.items():
            b = QPushButton(tr("开启{permission}", permission=tr(name)))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
            pl.addWidget(b)
            self.perm_btns[name] = b

        # 对话区 + 输入区
        self.view = ChatView(self.fill_example, self.theme)
        self.composer = Composer(self.send, self.theme["muted"])
        self.input = self.composer.edit
        self.composer.btn.clicked.connect(self.send_or_stop)
        self.status = QLabel(tr("就绪"))
        self.status.setObjectName("status")
        shrink = QPushButton(tr("收起到角落 {shortcut}", shortcut=QKeySequence(COMPACT_SHORTCUT).toString(QKeySequence.SequenceFormat.NativeText)))
        shrink.setObjectName("link")
        shrink.setCursor(Qt.CursorShape.PointingHandCursor)
        shrink.setToolTip(tr("缩成屏幕右下角的小条，不挡页面（开着「台前调度」时系统最小化可能无效，用这个代替）"))
        shrink.clicked.connect(self.enter_mini)
        foot = QHBoxLayout()
        foot.setContentsMargins(6, 0, 2, 0)
        foot.addWidget(self.status, 1)
        foot.addWidget(shrink)

        self.full_panel = QWidget()
        full = QVBoxLayout(self.full_panel)
        full.setContentsMargins(14, 12, 14, 10)
        full.setSpacing(8)
        full.addLayout(top)
        full.addWidget(self.settings_card)
        full.addWidget(self.perm_bar)
        full.addWidget(self.view, 1)
        full.addWidget(self.composer)
        full.addLayout(foot)

        # 执行时的小条
        self.mini_panel = QFrame()
        self.mini_panel.setObjectName("mini")
        ml = QHBoxLayout(self.mini_panel)
        ml.setContentsMargins(12, 4, 6, 4)
        self.mini_status = QLabel(tr("正在处理…"))
        self.mini_status.setMinimumWidth(10)
        expand_btn = QPushButton(tr("展开"))
        expand_btn.clicked.connect(self.exit_mini)
        self.mini_stop = QPushButton(tr("停止"))
        self.mini_stop.clicked.connect(self.stop)
        self.mini_stop.hide()
        ml.addWidget(self.mini_status, 1)
        ml.addWidget(expand_btn)
        ml.addWidget(self.mini_stop)
        self.mini_panel.hide()

        central = QWidget()
        central.setObjectName("root")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.full_panel)
        mini_wrap = QHBoxLayout()
        mini_wrap.setContentsMargins(6, 6, 6, 6)
        mini_wrap.addWidget(self.mini_panel)
        root.addLayout(mini_wrap)
        self.setCentralWidget(central)
        self.compact_shortcut = QShortcut(QKeySequence(COMPACT_SHORTCUT), self)
        self.compact_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.compact_shortcut.activated.connect(lambda: self.exit_mini() if self.mini else self.enter_mini())

        self.setStyleSheet(stylesheet(self.theme))
        self.apply_icons()
        QApplication.instance().styleHints().colorSchemeChanged.connect(lambda _: self.apply_theme())

        # 信号
        self.bridge.text.connect(self.on_text)
        self.bridge.tool.connect(self.on_tool)
        self.bridge.tool_result.connect(self.on_tool_result)
        self.bridge.done.connect(lambda s: self.finish(s))
        self.bridge.error.connect(lambda s: self.finish(s, error=True))
        self.bridge.model.connect(self.on_model)
        self.bridge.reasoning.connect(self.on_reasoning)
        self.bridge.busy.connect(lambda: None if self.running else self.set_running(True))
        self.model_box.currentTextChanged.connect(lambda _: self.on_model_choice())

        # 恢复设置
        self.backend_box.setCurrentIndex(max(0, self.backend_box.findData(self.settings.value("backend", "本机 Claude Code"))))
        self.fill_models()
        self.model_box.setCurrentText(tr(self.settings.value(f"models/{self.backend_name()}",
                                                         self.settings.value("model", self.model_box.itemText(0)))))
        self.confirm_box.setChecked(self.settings.value("confirm", True, type=bool))
        self.delete_confirm_box.setChecked(self.settings.value("confirm_delete", False, type=bool))
        self.refocus_box.setChecked(self.settings.value("refocus", True, type=bool))
        self.mini_box.setChecked(self.settings.value("mini", True, type=bool))
        self.pin_box.setChecked(self.settings.value("pin", False, type=bool))
        self.backend_box.currentTextChanged.connect(lambda _: self.fill_models())
        self.effort_box.currentIndexChanged.connect(lambda _: self.save_settings())
        self.pin_box.toggled.connect(self.apply_pin)
        self.apply_pin(self.pin_box.isChecked())
        for w in (self.confirm_box, self.delete_confirm_box, self.refocus_box, self.mini_box, self.pin_box):
            w.toggled.connect(lambda _: self.save_settings())

        # 打开时接着上次的对话
        self.chats = chat_store.list_chats()
        self.load_chat(self.chats[0] if self.chats else chat_store.Chat(), resumed=bool(self.chats))

        self.update_model_note()
        self.set_status(f"就绪 · {self.model_label()}")
        self.input.setFocus()
        self.check_permissions(prompt=not bool(os.environ.get("MACCTRL_GUI_SMOKE")))
        self.front_timer = QTimer(self, timeout=self.track_front, interval=700)
        self.front_timer.start()
        self.perm_timer = QTimer(self, timeout=self.check_permissions, interval=3000)
        self.perm_timer.start()

    # ------------------------------------------------------------ 外观
    def backend_name(self):
        return self.backend_box.currentData() or "本机 Claude Code"

    def model_value(self):
        selected = self.model_box.currentText()
        return "（默认）" if selected == tr("（默认）") else selected

    def change_language(self):
        selected = self.language_box.currentData()
        if selected == i18n.language():
            return
        if self.running or (self.updater.worker and self.updater.worker.isRunning()):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, tr("语言"), tr("切换语言前请先完成或停止当前任务，并等待更新下载完成。"))
            self.language_box.blockSignals(True)
            self.language_box.setCurrentIndex(self.language_box.findData(i18n.language()))
            self.language_box.blockSignals(False)
            return
        self.save_state()
        self.save_settings()
        self.settings.setValue("language", selected)
        self.settings.sync()
        draft, files, geometry = self.input.toPlainText(), list(self.composer.files), self.geometry()
        if self.backend:
            self.backend.shutdown()
        i18n.set_language(selected)
        replacement = MainWindow()
        replacement.setGeometry(geometry)
        replacement.input.setPlainText(draft)
        replacement.composer.add_files(files)
        replacement.gear_btn.setChecked(True)
        QApplication.instance().main_window = replacement
        if shortcut := getattr(QApplication.instance(), 'global_shortcut', None):
            shortcut.sync_window()
        if tray := getattr(QApplication.instance(), 'desktop_tray', None):
            tray.refresh()
        replacement.show()
        self._replacing = True
        self.close()
        self.deleteLater()

    def apply_theme(self):
        dark = QApplication.instance().styleHints().colorScheme() != Qt.ColorScheme.Light
        self.theme = THEMES["dark" if dark else "light"]
        self.view.theme = self.theme
        self.setStyleSheet(stylesheet(self.theme))
        self.apply_icons()

    def apply_icons(self):
        for name, b in self.icon_btns.items():
            b.setIcon(QIcon(svg_icon(name, self.theme["text"])))
        self.composer.set_icon_color(self.theme["muted"])

    # 整个窗口都能拖入文件
    def dragEnterEvent(self, e):
        if local_files(e.mimeData()) or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.composer.edit.insertFromMimeData(e.mimeData())
        e.acceptProposedAction()

    def apply_pin(self, on):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()

    def _model_key(self):
        return f"resolved/{self.backend_name()}/{self.model_value()}"

    def update_model_note(self):
        """模型框下方显示这个选项实际对应的模型（取自上一次运行时 Claude 的报告）。"""
        real = self.settings.value(self._model_key(), "")
        if real:
            self.model_note.setText(tr(f"实际使用：{pretty_model(real)}　·　{real}"))
        else:
            self.model_note.setText(tr("实际使用的模型会在第一次运行后显示"))
        if self.backend_name() == "本机 Codex" and getattr(self, "real_effort", ""):
            self.model_note.setText(tr(self.model_note.text() + f"\n本轮推理配置：{self.real_effort}"))
        if self.backend_name() == "本机 Codex":
            self.model_note.setText(tr(self.model_note.text() + "\n模型在所选档位内按需思考，应用不自动切档"))

    def on_model_choice(self):
        self.real_effort = ""
        if not self.model_box.signalsBlocked():
            self.settings.setValue(f"models/{self.backend_name()}", self.model_value())
        self.fill_efforts()
        self.update_model_note()
        if not self.running:
            self.real_model = None
            self.set_status(f"就绪 · {self.model_label()}")

    def on_model(self, model_id):
        self.real_model = model_id
        self.settings.setValue(self._model_key(), model_id)
        self.update_model_note()
        if self.running:
            self.set_status(f"正在处理… · {pretty_model(model_id)}")

    def on_reasoning(self, effort):
        self.real_effort = tr(effort)
        self.update_model_note()
        if self.running:
            self.set_status(f"正在处理… · {self.model_label()} · 推理 {tr(effort)}")

    def fill_models(self):
        name = self.backend_name()
        self.model_box.blockSignals(True)
        self.model_box.clear()
        self.model_box.addItems([tr(value) for value in (["（默认）"] + codex_models() if name == "本机 Codex" else BACKENDS[name])])
        self.model_box.setCurrentText(tr(self.settings.value(f"models/{name}", self.model_box.itemText(0))))
        self.model_box.blockSignals(False)
        self.real_model = None
        self.real_effort = ""
        self.fill_efforts()
        self.update_model_note()

    def _effort_key(self):
        return f"reasoning/{self.backend_name()}/{self.model_value()}"

    def fill_efforts(self):
        codex = self.backend_name() == "本机 Codex"
        self.effort_label.setVisible(codex)
        self.effort_box.setVisible(codex)
        self.effort_box.blockSignals(True)
        self.effort_box.clear()
        self.effort_box.addItem(tr("默认（沿用 Codex 配置）"), "")
        if codex:
            for level in codex_reasoning_levels(self.model_value().strip()):
                self.effort_box.addItem(level, level)
            selected = self.settings.value(self._effort_key(), "")
            if selected == "auto":
                selected = ""
                self.settings.setValue(self._effort_key(), "")
            self.effort_box.setCurrentIndex(max(0, self.effort_box.findData(selected)))
        self.effort_box.blockSignals(False)

    def fill_example(self, text):
        self.input.setPlainText(text)
        self.input.setFocus()
        self.input.moveCursor(self.input.textCursor().MoveOperation.End)

    def add(self, kind, text, save=True):
        if save and self.chat is not None:
            self.chat.add(kind, text)
        self.shown.append((kind, text))
        self.view.add(kind, text)

    def check_permissions(self, prompt=False):
        missing = []
        state = mac_tools.permissions()
        if not state["accessibility"]:
            missing.append("辅助功能")
            if prompt and sys.platform == "darwin":
                AX.AXIsProcessTrustedWithOptions({AX.kAXTrustedCheckOptionPrompt: True})
        if not state["screen_recording"]:
            missing.append("屏幕录制")
        self.perm_bar.setVisible(bool(missing))
        for name, b in self.perm_btns.items():
            b.setVisible(name in missing)
        if missing:
            if sys.platform == "darwin":
                self.perm_label.setText(tr("缺少「{permissions}」权限，部分操作受限",
                                           permissions=", ".join(tr(name) for name in missing)))
            else:
                self.perm_label.setText(mac_tools.permission_hint(missing))
            self.perm_label.setToolTip(mac_tools.permission_hint(missing))

    def track_front(self):
        a = mac_tools.frontmost_app()
        if a:
            self.last_front = (a["name"], a["pid"])

    def set_api_key(self):
        key, ok = QInputDialog.getText(self, "Claude API Key",
                                       tr("只在使用「Claude API」时需要（留空则读取环境变量 ANTHROPIC_API_KEY）："),
                                       QLineEdit.EchoMode.Password, self.settings.value("api_key", ""))
        if ok:
            self.settings.setValue("api_key", key.strip())
            self.backend_key = None

    # ------------------------------------------------------------ 小条模式（执行时不挡页面）
    def enter_mini(self):
        if self.mini:
            return
        self.mini = True
        self.full_geom = self.geometry()
        self.full_panel.hide()
        self.mini_panel.show()
        self.setMinimumSize(0, 0)
        self.resize(MINI_W, MINI_H)
        scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        fh = self.frameGeometry().height() - self.geometry().height()
        self.move(scr.right() - MINI_W - 12, scr.bottom() - MINI_H - fh - 12)

    def exit_mini(self):
        if not self.mini:
            return
        self.mini = False
        self.mini_panel.hide()
        self.full_panel.show()
        self.setMinimumWidth(420)
        if self.full_geom is not None:
            self.setGeometry(self.full_geom)

    # ------------------------------------------------------------ 对话管理
    def refresh_history(self):
        self.chats = chat_store.list_chats()
        self.history_box.blockSignals(True)
        self.history_box.clear()
        items = list(self.chats)
        if self.chat is not None and self.chat.folder is None:
            items.insert(0, self.chat)
        for c in items:
            stamp = time.strftime("%m-%d", time.localtime(c.data.get("updated", time.time())))
            self.history_box.addItem(f"{stamp}　{c.title}" if c.folder else tr("新对话"), c)
        for i in range(self.history_box.count()):
            c = self.history_box.itemData(i)
            if c is self.chat or (c.folder and self.chat and c.folder == self.chat.folder):
                self.history_box.setCurrentIndex(i)
        self.history_box.blockSignals(False)

    def load_chat(self, chat, resumed=False):
        self.chat = chat
        if self.backend:
            self.backend.shutdown()
        self.backend = None           # 换对话后按新对话的状态重建后端
        self.backend_key = None
        self.shown = [tuple(e) for e in chat.entries]
        self.view.clear()
        if not chat.entries:
            self.view.show_empty()
        else:
            for k, t in self.shown:
                self.view.add(k, t)
            if resumed:
                self.add("meta", "已打开上次的对话，可以直接接着说；换话题点右上角 ＋。", save=False)
        self.refresh_history()

    def change_global_shortcut(self, enabled):
        self.settings.setValue('global_compact_shortcut', enabled)
        if shortcut := getattr(QApplication.instance(), 'global_shortcut', None):
            shortcut.set_enabled(enabled)

    def on_history(self, index):
        chat = self.history_box.itemData(index)
        if self.running or chat is None or chat is self.chat:
            self.refresh_history()
            return
        self.load_chat(chat)

    def new_chat(self):
        if self.running:
            return
        self.load_chat(chat_store.Chat())
        self.input.setFocus()

    def open_folder(self):
        folder = self.chat.folder if self.chat and self.chat.folder else chat_store.ROOT
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ------------------------------------------------------------ 发送 / 执行
    def save_settings(self):
        if self.backend_name() == "本机 Codex":
            self.settings.setValue(self._effort_key(), self.effort_box.currentData() or "")
        for k, v in (("backend", self.backend_name()), ("model", self.model_value()),
                     ("confirm", self.confirm_box.isChecked()), ("refocus", self.refocus_box.isChecked()),
                     ("confirm_delete", self.delete_confirm_box.isChecked()),
                     ("mini", self.mini_box.isChecked()), ("pin", self.pin_box.isChecked())):
            self.settings.setValue(k, v)

    def ensure_backend(self):
        name = self.backend_name()
        model = self.model_value().strip()
        model = "" if model.startswith("（") else model
        key = (name, model, self.confirm_box.isChecked(), self.settings.value("api_key", ""),
               self.delete_confirm_box.isChecked(), self.effort_box.currentData() or "" if name == "本机 Codex" else "")
        if key != self.backend_key or not self.backend:
            if self.backend:
                self.backend.shutdown()      # 结束旧的常驻进程
            if name == "本机 Claude Code":
                self.backend = ClaudeCodeBackend(self.bridge, model, key[2], os.getpid(), confirm_delete=key[4])
            elif name == "本机 Codex":
                self.backend = CodexBackend(self.bridge, model, key[2], os.getpid(), confirm_delete=key[4],
                                            reasoning_effort=key[5])
            else:
                self.backend = ApiBackend(self.bridge, model, key[2], os.getpid(), key[3], confirm_delete=key[4])
            self.backend.load(self.chat.state(name))
            self.backend_key = key
        self.save_settings()

    def save_state(self):
        if self.backend and self.chat:
            self.chat.set_state(self.backend_key[0], self.backend.state())
            self.chat.save()

    def send_or_stop(self):
        if self.running and not self.composer.has_content():
            self.stop()
        else:
            self.send()

    def stop(self):
        if self.running and self.backend:
            self.backend.stop()
            self.set_status("正在停止…")

    def send(self):
        text = self.input.toPlainText().strip()
        if not (text or self.composer.files):
            return
        queued = self.running          # 执行中继续发：直接送进当前会话，Claude 会在这一步结束后看到
        if not queued:
            self.ensure_backend()
            self.real_model = None
        self.input.clear()
        files = self.composer.take_files()
        if not text:
            text = "请看看这些文件。"
        if not self.chat.entries:
            self.view.clear()          # 去掉空白页的示例
        self.chat.maybe_retitle(text)
        folder = self.chat.ensure_folder(text)
        files = self.store_files(files, folder)
        if files:
            self.add("files", json.dumps([str(f) for f in files], ensure_ascii=False))
        self.add("user", text)
        front = self.last_front[0] if self.last_front else None
        self.backend.send(text, front, str(folder), [str(f) for f in files])
        if queued:
            self.add("meta", "已加入当前对话，助手会继续处理这条消息", save=False)
            return
        self.refresh_history()
        self.set_running(True)
        if self.mini_box.isChecked():
            self.enter_mini()
        if self.refocus_box.isChecked() and self.last_front:
            try:
                mac_tools.t_activate_app(self.last_front[0])
            except Exception:
                pass

    @staticmethod
    def store_files(files, folder):
        """附件复制到「对话文件夹/附件」里保存，之后就算原文件被删也还能看、还能继续问。"""
        if not files:
            return []
        dest = folder / "附件"
        dest.mkdir(exist_ok=True)
        out = []
        for f in files:
            if dest in f.parents:
                out.append(f)
                continue
            target = dest / f.name
            i = 2
            while target.exists():
                target = dest / f"{f.stem} ({i}){f.suffix}"
                i += 1
            shutil.copy2(f, target)
            out.append(target)
        return out

    def set_status(self, text):
        self.status.setText(tr(text))
        self.mini_status.setText(tr(text))

    def set_running(self, on):
        self.running = on
        self.composer.set_running(on)
        busy_flag = chat_store.ROOT / ".busy"        # 外部（比如重启脚本）据此判断是否正在执行任务
        try:
            busy_flag.write_text(str(os.getpid())) if on else busy_flag.unlink(missing_ok=True)
        except OSError:
            pass
        self.mini_stop.setVisible(on)
        for w in (self.backend_box, self.model_box, self.effort_box, self.confirm_box, self.delete_confirm_box, self.history_box, self.language_box):
            w.setEnabled(not on)
        self.set_status(("正在处理…" if on else "就绪") + f" · {self.model_label()}")

    def model_label(self):
        """状态栏里的模型名：优先用 Claude 报告的实际模型，其次是上次记下的。"""
        real = getattr(self, "real_model", None) or self.settings.value(self._model_key(), "")
        return pretty_model(real) if real else f"{tr(self.backend_name())} · {tr(self.model_value())}"

    def on_text(self, text):
        self.add("bot", text)
        self.save_state()
        first = text.strip().splitlines()[0] if text.strip() else ""
        self.mini_status.setText(first[:40])

    def on_tool(self, name, args):
        self.add("tool", f"{name} {args}")
        self.set_status(tool_line(f"{name} {args}"))

    def on_tool_result(self, is_error, summary):
        if is_error:
            self.add("err", summary)

    def finish(self, info, error=False):
        self.save_state()
        original_info = info
        info = tr(info)
        if not error and original_info != "已停止" and getattr(self, "real_model", None):
            info += f" · {pretty_model(self.real_model)}"
        self.add("meta_err" if error else "meta", info)
        self.set_running(False)
        self.exit_mini()
        self.refresh_history()

    def request_quit(self):
        if self.updater.worker and self.updater.worker.isRunning():
            return
        application = QApplication.instance()
        application._quitting = True
        self.close()
        application.quit()

    def closeEvent(self, e):
        application = QApplication.instance()
        tray = getattr(application, 'desktop_tray', None)
        if (tray and tray.icon.isVisible() and not getattr(application, '_quitting', False)
                and not getattr(self, '_replacing', False)):
            self.save_state()
            self.hide()
            e.ignore()
            return
        if self.updater.worker and self.updater.worker.isRunning():
            e.ignore()
            return
        if self.backend:
            self.backend.shutdown()
        self.save_state()
        super().closeEvent(e)


def _log_exception(kind, value, tb):
    """PyQt6 遇到未处理的异常默认直接终止程序；装上自定义 excepthook 后改为只记日志、程序继续运行。"""
    import traceback
    sys.stderr.write(time.strftime("[%Y-%m-%d %H:%M:%S] 未处理的错误：\n") + "".join(traceback.format_exception(kind, value, tb)))
    sys.stderr.flush()


def main():
    mac_tools.SELF_PID = os.getpid()
    sys.excepthook = _log_exception
    script = os.environ.get("MACCTRL_SELFTEST")
    if script:   # 自检：借用本 App 的系统权限跑测试脚本 —— open -n "Mac 控制台.app" --env MACCTRL_SELFTEST=<脚本路径>
        import runpy
        runpy.run_path(script, run_name="__main__")
        return
    app = QApplication(sys.argv)
    if os.environ.get("MACCTRL_GUI_SMOKE"):
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                          os.environ["MAC_CTRL_DATA_DIR"])
    app.setApplicationName("Mac 控制台")
    app.setWindowIcon(QIcon(str(HERE / 'assets/app-icon.png')))
    if sys.platform == 'darwin':
        from AppKit import NSApplication, NSImage, NSApplicationActivationPolicyRegular
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyRegular)
        image = NSImage.alloc().initWithContentsOfFile_(str(HERE / 'assets/app-icon.png'))
        NSApplication.sharedApplication().setApplicationIconImage_(image)
    settings = app_settings()
    default_language = "zh_CN" if QLocale.system().name().startswith("zh") else "en"
    i18n.set_language(os.environ.get("MAC_CTRL_LANGUAGE") or settings.value("language", default_language))
    f = QFont(".AppleSystemUIFont")
    f.setPointSize(13)
    app.setFont(f)
    w = MainWindow()
    app.main_window = w
    from desktop_ui import DesktopTray
    app.desktop_tray = DesktopTray(app)
    app.aboutToQuit.connect(app.desktop_tray.cleanup)
    if sys.platform == 'darwin':
        from global_shortcut import GlobalShortcut
        app.global_shortcut = GlobalShortcut(app, app.desktop_tray)
    w.show()
    if os.environ.get("MACCTRL_GUI_SMOKE"):
        w.gear_btn.setChecked(True)
        if image := os.environ.get("MACCTRL_SMOKE_IMAGE"):
            QTimer.singleShot(350, lambda: w.grab().save(image))
        if os.environ.get("MACCTRL_LANGUAGE_TEST"):
            from gui_smoke import schedule
            schedule(app)
        else:
            QTimer.singleShot(700, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
