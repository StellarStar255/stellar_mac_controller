- Added **persistent scheduled tasks** to all three backends. Ask for a one-time check, such as “Check WeChat in 30 minutes,” or a recurring check, such as “Check WeChat every 30 minutes.”
- Tasks run automatically while the app stays open, save results to the original conversation, and attempt a desktop notification. Open **Scheduled tasks** in Settings or the tray menu to view, pause, resume, or cancel tasks.
- Tasks retain their creation-time backend, model, reasoning effort, and confirmation settings. Existing application permissions still apply. Draft messages are preserved while scheduled work runs.
- Sleep, macOS screen lock, and other assistant work delay execution. Missed occurrences are combined into one run per task. Pending tasks survive restart; interrupted running tasks are paused for review before manual resume. The app does not wake a sleeping computer or execute while quit.
- Improved macOS interface reading, including WeChat: try accessible text first, inspect navigation/content children when needed, and report when only window controls are readable.

新增持久化定时任务：支持“30 分钟后检查微信”和“每隔 30 分钟检查微信”，结果保存到原对话并尝试桌面通知。在设置或托盘的「定时任务」中查看、暂停、恢复和取消。程序需保持运行；睡眠、macOS 锁屏或忙碌时延后补跑一次。执行中被退出或崩溃打断的任务会暂停，检查结果后手动恢复。同时改进微信等程序的界面文字读取。

For manual DMG updates, quit the running app before replacing it. Linux desktop control requires X11. Local CLI backends require a separately installed and signed-in Claude Code or Codex CLI.

The macOS **DMGs and their apps are Developer ID signed, Apple notarized, and stapled**. Download the `macos-arm64.dmg` for Apple Silicon, including M5. Legacy PKG installers are not Developer ID Installer signed; use the DMG for the signed macOS download. Windows installers are not Authenticode signed. Normal system permission confirmations may still be required.

[English documentation](https://github.com/StellarStar255/stellar_mac_controller#readme) · [中文说明](https://github.com/StellarStar255/stellar_mac_controller/blob/main/README.zh-CN.md)
