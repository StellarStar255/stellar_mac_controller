English is now the default repository README, with a linked Chinese version.

- Switch between **English / 简体中文** in **Settings → Language**. The choice is remembered; conversations, drafts and attachments are preserved.
- Assistant responses and confirmation dialogs follow the selected language. Existing conversation content is kept unchanged.
- Self-contained installers for macOS ARM/Intel, Windows x64, and Linux x64 (`.deb` and per-user `.run`).
- In-app update downloads verify SHA-256 and size before opening the installer. Chats and settings are preserved.

Linux desktop control requires X11; Wayland is not supported yet. Windows/Linux use their own desktop tools, without macOS AppleScript/browser scripting. Local CLI backends still need a separately installed and signed-in Claude Code or Codex CLI; Claude API is also available.

Installers are not Apple Developer / Authenticode signed, and the macOS package is not notarized. System installation and permission confirmations may be required.

[English documentation](https://github.com/StellarStar255/stellar_mac_controller#readme) · [中文说明](https://github.com/StellarStar255/stellar_mac_controller/blob/main/README.zh-CN.md)
