# Mac Controller

[English](README.md) · [简体中文](README.zh-CN.md)

A desktop AI assistant that uses your own computer tools to operate apps. Supports macOS, Windows and Linux X11, with a PyQt6 interface, persistent conversations, file attachments and in-app updates.

## Install

Download the installer for your computer from the [latest release](https://github.com/StellarStar255/stellar_mac_controller/releases/latest). Python and the application dependencies are bundled.

| Platform | File | Installation |
| --- | --- | --- |
| macOS, Apple Silicon | `macos-arm64.pkg` | Double-click and follow the installer. Installs in Applications. |
| macOS, Intel | `macos-x64.pkg` | Double-click and follow the installer. Installs in Applications. |
| Windows 10/11, x64 | `windows-x64-setup.exe` | Double-click to install for your user and create a desktop shortcut. |
| Ubuntu/Debian, x64 | `linux-x64.deb` | Open with your system software installer. Ubuntu 22.04+ or equivalent. |
| Other Linux x64 / per-user install | `linux-x64.run` | Run `sh <downloaded-file>.run`. Launch from the applications menu. |

Installers do not currently have Apple Developer / Windows Authenticode distribution signatures. The macOS package is not notarized. Your operating system may require an installation confirmation. Published SHA-256 checksums verify download integrity; they are not publisher signatures.

### Updates

Open **Settings → Check for updates**. The app selects your platform's installer, downloads it, checks its SHA-256 and size, and opens the installer. Complete any system installation or administrator confirmation. Per-user Linux installations update in the user directory. Chats, attachments, notes and settings are kept outside the installation folder and preserved.

A failed download or checksum check leaves the existing version available.

### Language

Choose **Settings → Language → English / 简体中文**. The selection is remembered. The interface switches immediately while keeping the current conversation, unsent draft and attachments. Finish or stop the current task before switching. Assistant replies follow the selected language; existing messages and your file names are not translated.

On first launch, the language follows the system locale: Chinese for a Chinese locale, English otherwise.

## Choose a backend

- **Local Claude Code**: uses the installed and signed-in `claude` CLI. No API key is needed in this app.
- **Local Codex**: uses the installed and signed-in `codex` CLI. Run `codex login` first. No Claude API key is needed.
- **Claude API**: enter your own API key in Settings, or set `ANTHROPIC_API_KEY`.

CLI backends require the corresponding CLI to be installed separately and available on PATH. No accounts or credentials are bundled.

Select a model or enter a model ID. Each backend remembers its model selection. Codex also provides the reasoning effort levels supported by its local model catalog. Default preserves the CLI setting. The app does not automatically switch reasoning effort.

Codex runs through `exec --json` and resumes conversations using their thread IDs. Only this project's `mac` MCP service is enabled in its child process. Inherited plugins and other MCP services are disabled for that process. Your global ChatGPT/Codex configuration is not changed. The bundled executable also runs the MCP service, so a separate Python installation is unnecessary.

## Platform capabilities

| Capability | macOS | Windows | Linux X11 |
| --- | --- | --- | --- |
| Commands, files and persistent notes | Yes | Yes | Yes |
| Screenshots, mouse and keyboard | Yes | Yes | Yes |
| Numbered accessibility elements | Native Accessibility | UI Automation | Screenshot / coordinate fallback |
| AppleScript | Yes | No | No |
| Browser `web_read` / `web_act` via Apple events | Yes | No | No |

On Windows and Linux, use screenshots, mouse and keyboard for browser tasks. Windows processes with normal privileges cannot control administrator windows. Linux Wayland desktop control is not currently supported; select an Xorg/X11 session at login. Keep the desktop unlocked while using interface tools.

### macOS permissions

Enable **Accessibility** and **Screen Recording** for Mac Controller in **System Settings → Privacy & Security**. For source runs, macOS may attribute permission to the terminal that launched Python. After changing Screen Recording, fully quit and reopen that responsible app. AppleScript automation may also prompt for permission.

Browser scripting on macOS requires “Allow JavaScript from Apple Events” in the browser's developer settings.

### Linux dependencies

Linux desktop control requires a graphical X11 session. The `.deb` declares its system dependencies. For a `.run` installation on Ubuntu, install:

```bash
sudo apt-get install libegl1 libopengl0 libxcb-cursor0 libxkbcommon-x11-0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 \
  libxcb-shape0 libxcb-xfixes0 libxcb-sync1 libxcb-randr0 libxcb-xkb1 libxcb-util1 \
  libx11-xcb1 libxrender1 libxi6 libsm6 libice6 xclip wmctrl xdotool
```

## Conversations and files

Conversations are saved under `~/Documents/Mac 控制台/`, including a readable Markdown transcript and any attachments. Return to a previous chat to continue. The selected backend's session state is preserved across restarts. Deleting a conversation folder removes that conversation.

Paste or drag images, PDFs and files into the composer, or use the attachment button. Research notes and generated files are saved in the conversation's folder. Messages sent while the assistant is working are queued.

The optional compact window keeps the controller out of the way while a task runs. Risky-action and deletion confirmations are configured in Settings. Turning confirmations off allows those actions without the app's confirmation dialog. These settings do not override operating-system or external-service restrictions.

API keys entered in Settings are stored in the operating system's application settings, not in the repository. Treat your local settings and conversation folders as private data. Screenshots, local app bundles, caches, conversation histories and credential files are excluded from Git.

## Run from source

Use Python 3.11 or newer:

```bash
python3 -m pip install -r requirements.txt
python3 launcher.py
```

On macOS, `python3 make_app.py` creates a local double-click launcher tied to that computer's Python and project location. This development launcher is different from the self-contained release installer.

## Build and release

On the target operating system:

```bash
python -m pip install -r requirements.txt pyinstaller==6.21.0
python -m unittest discover -s tests -v
python packaging/build.py
python packaging/smoke.py
```

Windows also requires Inno Setup 6. Linux builds require `dpkg-deb`; run GUI smoke tests in an X11 session or with `xvfb-run -a`.

The version is defined in `version.py`. Push a matching `vX.Y.Z` tag to build on native Mac ARM, Mac Intel, Windows x64 and Linux x64 runners. GitHub Actions publishes the installers, `SHA256SUMS` and `update-manifest.json` only after all builds and smoke tests pass. A manual workflow run performs build validation without publishing.

Main files: `app.py` (interface), `i18n.py` (translations), `backends.py` (AI backends), `mac_tools.py` / `desktop_tools.py` (computer tools), `mcp_server.py` (stdio MCP), `chat_store.py` (conversations), `updater.py` (verified downloads), and `packaging/` (installers and smoke tests).
