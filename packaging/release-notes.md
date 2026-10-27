首个三平台安装包版本，内置 Python 运行环境。

- macOS Apple Silicon：`macos-arm64.pkg`
- macOS Intel：`macos-x64.pkg`
- Windows 10/11 x64：`windows-x64-setup.exe`
- Ubuntu/Debian x64（Ubuntu 22.04+ / 相当版本，X11）：`linux-x64.deb`，双击用系统软件安装器安装
- 其它 Linux x64 / 用户目录安装：`linux-x64.run`，下载后运行 `sh 文件名.run`

在设置中点击「检查更新」，即可下载并校验新版本安装包，交给本机安装程序升级。对话、附件及设置保留。

macOS 保留原生辅助功能、AppleScript 和浏览器工具；Windows 增加 UI Automation 和鼠标键盘操作；Linux 提供 X11 截图、鼠标键盘、命令及笔记工具。Linux Wayland 暂不支持桌面控制，Windows/Linux 不提供 AppleScript 和 macOS 浏览器脚本工具。

Claude Code / Codex CLI 仍需另外安装并登录，也可以配置 Claude API Key。

安装包尚未使用 Apple Developer / Windows Authenticode 证书签名，首次安装可能出现系统确认提示；macOS 包也未做 Apple 公证。系统授权和安装确认仍需用户完成。Linux 图形桌面需要系统的 Qt/X11 依赖（见 README）。SHA256SUMS 提供下载完整性校验。
