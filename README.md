# Mac 控制台（stellar_mac_controller）

用一句中文让助手直接使用这台 Mac 上的程序。PyQt6 界面，三种“大脑”可切换：

- **本机 Claude Code**（默认）：调用已登录的 `claude` 命令，不需要 API Key，费用走你的 Claude Code 账号。
- **Claude API**：需要 `ANTHROPIC_API_KEY`（或点界面上的「API Key」填写），默认模型 `claude-opus-5`。
- **本机 Codex**：调用已安装、已登录的 `codex` 命令，使用 Codex CLI 的登录配置，不需要填写 Claude API Key。首次使用先执行 `codex login`。

点右上角设置按钮，在「大脑」选择后端，在「模型」选择或直接输入模型 ID。Codex 下拉选项来自本机 CLI 的模型缓存；「（默认）」沿用 CLI 的配置。模型是否可用取决于登录账号。每个后端分别记住模型选择；Codex 历史对话会按会话 ID 续聊，执行中追加的消息按顺序处理。

Codex 还可选择「推理强度」：`low` 偏快，`medium` 平衡，`high` 及以上通常思考更深入、耗时更多。已知模型按本机模型目录列出支持的档位；自定义模型和默认模型提供常用的 low / medium / high，是否支持由 CLI 验证。「默认」不覆盖 Codex 配置。每个模型分别记住强度，续聊也会应用新选择。配置对应官方的 [`model_reasoning_effort`](https://learn.chatgpt.com/docs/config-file/config-reference)。

应用不根据关键词、字数或附件数量估计难度，不自动切换推理档位。推理模型本身会在所选档位内按任务难度调整实际思考量，详见 [OpenAI 推理说明](https://developers.openai.com/api/docs/guides/reasoning)。界面显示的是推理配置，不代表测量到的实际思考量。旧版规则自动模式已移除，之前保存的 auto 选项会回到 CLI 默认，历史会话继续保留。

Codex 通过 `exec --json` 接入，Mac 操作统一使用本项目的 MCP 工具；原生 shell 工具关闭，原生命令沙箱只读，确认由 Mac 工具的设置处理。调用方式参考 [OpenAI 官方非交互模式文档](https://learn.chatgpt.com/docs/non-interactive-mode)。

本机 Codex 子进程会禁用继承的插件和其它 MCP 服务，只启用本项目的 `mac` 服务；账号、模型配置及 ChatGPT 本身的配置保持不变。若 `mac` 服务无法启动，本轮直接报错，不自动换用其它电脑操作工具。辅助功能、屏幕录制及危险操作确认仍由 Mac 控制台自己的权限和设置处理。

旧版本若出现 `Computer Use was not approved to use WeChat`，说明调用到了额外继承的 Computer Use 工具，不代表微信未登录，也不能据此判断 macOS 权限缺失。更新后重启控制台再检查调用工具；不能切换工具绕过已经拒绝的应用访问限制。

## 运行

需要 macOS 和 Python 3.11 或更高版本。

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

也可以执行 `python3 make_app.py`，在本机生成可双击启动的「Mac 控制台.app」。生成的 App 会记录当前 Python 和项目路径，请在使用的电脑上生成；仓库不包含本机 App、截图、对话记录或凭据。

第一次运行需要在 **系统设置 → 隐私与安全性** 里给启动它的终端（或 Python）打开：
- **辅助功能**：读取界面元素、模拟鼠标键盘
- **屏幕与系统音频录制**：截图

系统按「负责进程」判定权限：从终端启动时要授权的是**那个终端 App**（缺权限时提示条会点名），不是 Python。
屏幕录制要**完全退出并重新打开该终端**才生效，只重启本程序不够。开关已打开仍无效时，多半是旧版本留下的授权记录：
在列表里选中点「−」删掉重新添加，或执行 `tccutil reset Accessibility <bundle id>`（屏幕录制用 `ScreenCapture`）。
没有权限时仍可用 AppleScript / 终端命令完成大部分事情。

## 发图片、PDF 给 Claude 看

- 在输入框里 **⌘V** 直接粘贴截图或复制的图片；在访达里复制的文件也能粘贴。
- 把文件**拖到窗口上**，或点输入框左边的**回形针**选择文件。
- 发送后附件会复制到「对话文件夹/附件」里保存；本机 Claude Code 用它自带的只读 Read 工具查看（能看图、读 PDF），API 模式直接把图片 / PDF 附在消息里。Word、Excel 等由 Claude 用命令转换后再读。

## 对话保存与继续

- 每个对话自动保存在 **文稿 / Mac 控制台 / <日期 标题>/**，打开程序时自动回到上一次的对话，也可以在顶部「对话」下拉框里切换历史对话接着聊。
- 这个文件夹就是该对话的工作文件夹：下载、生成的文件默认放这里；做调研时 Claude 会边做边把要点和来源写进笔记（如 `调研笔记.md`、`总结.md`）。
- `对话记录.md` 是整理好的对话文本，不开程序也能在访达里直接看。
- 删掉文件夹就等于删掉这个对话。以前的 Claude Code 会话可以导入：`python3 chat_store.py import <session_id>`

## 执行时不挡页面

- 任务执行时窗口自动缩成屏幕右下角的小条（可在选项里关掉），做完恢复原样；小条上可以「展开」查看细节或「停止」。
- 截图、以及点击位置正好被控制台盖住时，会临时隐藏控制台再操作，不抢焦点。

## 它是怎么操作程序的

按优先级（能用前面的就不用后面的，截图是最后手段）：

1. **AppleScript / 终端命令**：访达、音乐、备忘录、日历、提醒事项、文件、下载等，不看屏幕。
2. **网页：`web_read` / `web_act`**：在浏览器里直接跑 JavaScript，一次读出网页的标题、网址、正文和带编号的链接 / 按钮 / 输入框，
   再按编号点击、填写提交、滚动、打开网址。不截图、不动鼠标，浏览器不在前台也能用（实测读一整页约 0.1 秒）。
   需要在浏览器里打开「允许 Apple 事件中的 JavaScript」（Comet / Chrome：View → Developer；Safari：开发 菜单）。
3. **辅助功能树**：`read_ui` 把其它程序窗口里的按钮、输入框、菜单项编上号，`ui_action` 按编号操作。
4. **截图 + 坐标**：微信这类自绘界面、游戏、需要看图片本身时才用。`screenshot(mark_elements=true)` 会把元素编号画在图上。

确认设置：普通文件删除默认直接执行，不再每次弹窗；需要时可勾选「删除文件前确认」（同时开启「危险操作前确认」）。sudo、清空废纸篓、发送消息/邮件、退出程序、关机、改系统设置等仍按「危险操作前确认」设置弹窗。关闭删除确认会放行命令或脚本中的删除内容操作，包括批量删除；同一命令若含 sudo 等其它风险仍会确认。这些设置控制本项目的工具弹窗，无法更改运行 Codex 客户端自身的权限提示。

不向密码框输入；输入文字和按回车分成两步；执行前重新核对元素是否还在；Claude API 单次任务最多 60 步。

## 文件

| 文件 | 作用 |
|---|---|
| `app.py` | PyQt6 界面 |
| `backends.py` | Claude Code / Codex CLI / Claude API 后端 |
| `mac_tools.py` | 所有 Mac 操作工具（三种后端共用） |
| `mcp_server.py` | 把工具包装成 MCP 服务，给 Claude Code 和 Codex 用 |
| `chat_store.py` | 对话存档（每个对话一个文件夹）、导入旧会话 |
| `make_app.py` | 生成可双击启动的 `Mac 控制台.app` |

单独调试某个工具：`python3 mac_tools.py read_ui '{"app": "Finder"}'`
