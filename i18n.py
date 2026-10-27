"""Application translations; internal backend keys and user content stay unchanged."""
import os
import re

_LANGUAGE = 'en'
CATALOG = {
    'Mac 控制台': 'Mac Controller',
    '新对话': 'New chat',
    '想让 Mac 做什么？': 'What would you like your Mac to do?',
    '想让电脑做什么？': 'What would you like your computer to do?',
    '用一句话告诉我，我会直接操作这台电脑上的程序。对话、笔记和下载的文件都会自动保存，下次可以接着做。': 'Describe a task and I will use your desktop apps. Chats, notes and downloads are saved so you can continue later.',
    '打开备忘录，新建一条笔记写上今天的待办': 'Open the notes app and create a note with today’s to-do list',
    '在小红书上调研一个话题，把要点整理成报告': 'Research a topic on the web and organize the findings into a report',
    '把下载文件夹里的 PDF 移到桌面的「资料」文件夹': 'Move PDFs from Downloads into a Documents folder on the Desktop',
    '音乐暂停，音量调到 30%': 'Pause music and set the volume to 30%',
    '大脑': 'Backend', '模型': 'Model', '推理强度': 'Reasoning effort',
    '本机 Claude Code': 'Local Claude Code', '本机 Codex': 'Local Codex',
    '（默认）': '(Default)', '默认（沿用 Codex 配置）': 'Default (Codex settings)',
    '打开本对话的文件夹（笔记、下载的文件都在这里）': 'Open this chat’s folder (notes and downloads)',
    '设置：大脑、模型、选项': 'Settings: backend, model and preferences',
    '选择模型，或直接输入模型 ID；每个后端分别记住选择': 'Choose or enter a model ID. Each backend remembers its selection.',
    '推理档位影响思考深度；模型会在所选档位内按需思考。low 偏快，medium 平衡，high 偏深入。默认沿用 Codex 配置；应用不自动切档。': 'Reasoning effort: low is faster, medium is balanced, and high thinks more deeply. Default uses Codex settings. Effort is never changed automatically.',
    '危险操作前确认': 'Confirm risky actions', '删除文件前确认': 'Confirm deletions',
    '发送后切回原程序': 'Return to previous app', '执行时收成小条': 'Compact view while working',
    '窗口置顶': 'Keep on top',
    '在管理员权限、发送消息、退出程序、关机等有风险的操作前弹窗确认；打开、查看、下载等直接执行': 'Ask before admin operations, sending messages, quitting apps or shutting down. Opening, viewing and downloading run directly.',
    '勾选后，命令或脚本删除内容前也会弹窗；需同时开启危险操作确认。清空废纸篓仍按危险操作确认': 'Ask before deleting content, including from scripts. Requires risky-action confirmation. Emptying Trash still follows risky-action confirmation.',
    '发送后自动切回你刚才在用的程序，方便它直接操作': 'Return focus to the app you were using after sending a message.',
    '任务执行期间窗口缩到屏幕右下角，不挡住要操作的页面；做完自动恢复': 'Use a small window at the bottom right while working, then restore it.',
    '收起到角落 ': 'Compact view ',
    '缩成屏幕右下角的小条，不挡页面（开着「台前调度」时系统最小化可能无效，用这个代替）': 'Show a compact window at the bottom right without covering the target app.',
    '展开': 'Expand', '停止': 'Stop', '发送': 'Send', '移除': 'Remove',
    '辅助功能': 'Accessibility', '屏幕录制': 'Screen Recording',
    '添加图片、PDF 或其它文件（也可以直接粘贴或拖进来）': 'Attach images, PDFs or other files (paste or drag and drop also works)',
    '添加文件': 'Add files',
    '常用文件 (*.png *.jpg *.jpeg *.gif *.webp *.heic *.pdf *.txt *.md *.csv *.docx *.xlsx *.pptx);;所有文件 (*)': 'Common files (*.png *.jpg *.jpeg *.gif *.webp *.heic *.pdf *.txt *.md *.csv *.docx *.xlsx *.pptx);;All files (*)',
    '描述你想做的事，可粘贴图片 / PDF…（Enter 发送）': 'Describe a task or paste an image / PDF… (Enter to send)',
    '继续输入，会在当前步骤结束后送达…（Enter 发送）': 'Add a message for the next step… (Enter to send)',
    '（点击打开）': ' (click to open)', '（1M 上下文）': ' (1M context)',
    '实际使用的模型会在第一次运行后显示': 'The actual model will appear after the first run.',
    '模型在所选档位内按需思考，应用不自动切档': 'The model adapts within the selected effort. The app does not switch effort automatically.',
    '只在使用「Claude API」时需要（留空则读取环境变量 ANTHROPIC_API_KEY）：': 'Required only for Claude API. Leave blank to use ANTHROPIC_API_KEY:',
    '已打开上次的对话，可以直接接着说；换话题点右上角 ＋。': 'Your previous chat is open. Continue here, or click + for a new topic.',
    '已加入当前对话，助手会继续处理这条消息': 'Queued in this chat. The assistant will process this message next.',
    '请看看这些文件。': 'Please review these files.',
    '就绪': 'Ready', '正在处理…': 'Working…', '正在停止…': 'Stopping…', '已停止': 'Stopped',
    '检查更新': 'Check for updates', '重试检查更新': 'Retry update check',
    '正在检查更新…': 'Checking for updates…', '正在下载安装包…': 'Downloading installer…',
    '更新': 'Update', '更新失败': 'Update failed', '发现新版本': 'Update available',
    '当前已是最新版本。': 'You are up to date.',
    '请先等待任务完成或停止任务，再更新。': 'Finish or stop the current task before updating.',
    '当前版本仍可继续使用。': 'You can continue using the current version.',
    '下载期间启动了新任务。请完成任务后再更新。': 'A task started during the download. Finish it before updating.',
    '切换语言前请先完成或停止当前任务，并等待更新下载完成。': 'Finish or stop the current task and wait for any update download before switching languages.',
    '语言': 'Language', '允许': 'Allow', '拒绝': 'Deny',
    '查看程序': 'List apps', '打开': 'Open', '切换到': 'Activate', '退出程序': 'Quit app',
    '运行脚本': 'Run script', '运行命令': 'Run command', '读取界面': 'Read interface',
    '操作元素': 'Use element', '截图': 'Screenshot', '点击': 'Click', '拖动': 'Drag',
    '输入文字': 'Type text', '按键': 'Press key', '滚动': 'Scroll', '等待': 'Wait',
    '写笔记': 'Write note', '读笔记': 'Read note', '查看文件': 'List files',
    '查看附件': 'Read attachment', '读网页': 'Read webpage', '操作网页': 'Use webpage',
    '填写': 'Fill', '提交': 'Submit', '后退': 'Back', '　点开查看': ' · click to expand',
    '更新只允许 HTTPS 下载。': 'Updates require HTTPS.', '更新元数据过大。': 'Update metadata is too large.',
    '安装包必须来自本项目的同一版本 Release。': 'The installer must come from the same release of this repository.',
    '此版本的安装包尚未准备完成，请稍后重试。': 'Installers for this release are not ready. Please try later.',
    '更新版本与清单不一致。': 'The release version does not match the update manifest.',
    '此版本暂时没有适合本机架构的安装包。': 'No installer is available for this architecture.',
    '更新清单缺少有效校验值。': 'The update manifest has no valid checksum.',
    '安装包大小无效。': 'Invalid installer size.', '安装包文件名无效。': 'Invalid installer filename.',
    '安装包超出大小限制。': 'The installer exceeds the download size limit.',
    '安装包校验失败，已取消安装。': 'Installer verification failed. Installation was canceled.',
    '暂不提供此系统架构的安装包。': 'This system architecture is not supported.',
    '执行了 {n} 步': '{n} steps', '，{n} 次出错': ', {n} errors',
    '检查更新 · v{version}': 'Check for updates · v{version}',
    '实际使用：{model}　·　{id}': 'Actual model: {model} · {id}',
    '本轮推理配置：{effort}': 'Reasoning effort: {effort}',
    '就绪 · {model}': 'Ready · {model}', '正在处理… · {model}': 'Working… · {model}',
    '完成 · {n} 轮 · {seconds} 秒': 'Completed · {n} turn(s) · {seconds}s',
    '完成 · {n} 轮 · {seconds} 秒 · ${cost}': 'Completed · {n} turn(s) · {seconds}s · ${cost}',
    '发现 v{version}。立即下载安装？\n安装时程序会退出，对话和设置会保留。': 'Version {version} is available. Download and install now?\nThe app will close for installation. Chats and settings are preserved.',
    '缺少「{permissions}」权限，部分操作受限': 'Permission required: {permissions}. Some actions are unavailable.',
    '开启{permission}': 'Enable {permission}',
    'Codex 执行失败：{message}': 'Codex failed: {message}',
    'Claude Code 异常退出（{code}）：{message}': 'Claude Code exited ({code}): {message}',
    '不支持的版本号：{version}': 'Unsupported version: {version}',
    '{filename}（点击打开）': '{filename} (click to open)',
    '{name}（1M 上下文）': '{name} (1M context)',
    '收起到角落 {shortcut}': 'Compact view {shortcut}',
    '正在处理… · {model} · 推理 {effort}': 'Working… · {model} · effort {effort}',
    '运行终端命令': 'Run terminal command', '管理员权限': 'Administrator access',
    '删除文件': 'Delete files', '批量删除文件': 'Delete multiple files',
    '同步时删除文件': 'Delete files during synchronization', '删除内容': 'Delete content',
    '清空废纸篓': 'Empty Trash', '发送消息/邮件': 'Send messages or email',
    '直接写磁盘': 'Write directly to disk', '抹掉/分区磁盘': 'Erase or partition a disk',
    '强制结束进程': 'Force-quit processes', '关机/重启': 'Shut down or restart',
    '停用系统服务': 'Disable system services', '不可恢复的 git 操作': 'Destructive Git operation',
    '卸载软件': 'Uninstall software', '修改系统设置': 'Change system settings',
    '批量改权限': 'Change multiple file permissions', '删除定时任务': 'Delete scheduled tasks',
    '向网络发送数据': 'Send data over the network', '发送邮件': 'Send email',
    '关机/重启/注销': 'Shut down, restart or log out', '抹掉内容': 'Erase content',
}


def set_language(language):
    global _LANGUAGE
    _LANGUAGE = 'zh_CN' if language in ('zh', 'zh_CN') else 'en'
    os.environ['MAC_CTRL_LANGUAGE'] = _LANGUAGE


def language():
    return os.environ.get('MAC_CTRL_LANGUAGE', _LANGUAGE)


def tr(source, **values):
    if language() != 'en':
        return source.format(**values) if values else source
    translated = CATALOG.get(source)
    if translated is not None:
        return translated.format(**values) if values else translated
    if values:
        return source.format(**values)
    # Support backend status messages that arrive already formatted over signals.
    for template, english in sorted(CATALOG.items(), key=lambda item: len(re.sub(r'\{\w+\}', '', item[0])), reverse=True):
        if '{' not in template:
            continue
        names = re.findall(r'\{(\w+)\}', template)
        pattern = re.escape(template)
        for name in names:
            pattern = pattern.replace(re.escape('{'+name+'}'), '(?P<'+name+'>.*?)')
        match = re.fullmatch(pattern, source, flags=re.S)
        if match:
            return english.format(**match.groupdict())
    if '\n' in source:
        return '\n'.join(tr(line) for line in source.split('\n'))
    return source
