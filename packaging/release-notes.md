- macOS now provides **DMG installers for Apple Silicon and Intel**: open the disk image and drag **Mac Controller.app** into **Applications**. PKG installers remain available for guided installation and in-app updates.
- A dedicated application icon appears in the Dock/taskbar. Windows executables and Linux application launchers also include the icon.
- Added a macOS menu bar / Windows and Linux system tray menu: **Open main window**, **Settings**, and **Quit**. Closing the window keeps the app running when a tray is available; choose Quit to exit.
- Tray labels follow the selected English / 简体中文 language. Conversations, settings and drafts are preserved.

For manual DMG updates, quit the running app before replacing it. Linux desktop control requires X11. Local CLI backends require a separately installed and signed-in Claude Code or Codex CLI.

The macOS **DMGs and their apps are Developer ID signed, Apple notarized, and stapled**. Download the `macos-arm64.dmg` for Apple Silicon, including M5. Legacy PKG installers are not Developer ID Installer signed; use the DMG for the signed macOS download. Windows installers are not Authenticode signed. Normal system permission confirmations may still be required.

[English documentation](https://github.com/StellarStar255/stellar_mac_controller#readme) · [中文说明](https://github.com/StellarStar255/stellar_mac_controller/blob/main/README.zh-CN.md)
