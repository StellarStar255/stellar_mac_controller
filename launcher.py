"""Frozen GUI entry point, also serving stdio MCP without opening a window."""
import os
from pathlib import Path
import sys


def main():
    # Desktop shortcuts do not inherit the interactive shell's executable paths.
    extra = [Path.home() / ".local/bin", Path.home() / ".npm-global/bin"]
    if sys.platform == "darwin":
        extra += [Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    elif sys.platform == "win32":
        extra += [Path(os.environ.get("APPDATA", str(Path.home()))) / "npm"]
    os.environ["PATH"] = os.pathsep.join([os.environ.get("PATH", ""), *(str(p) for p in extra)])
    if sys.platform == "darwin" and not (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")):
        from urllib.request import getproxies
        for protocol, proxy in getproxies().items():
            if protocol in {"http", "https"}:
                os.environ.setdefault(protocol + "_proxy", proxy)
    if "--mcp" in sys.argv:
        import mcp_server
        mcp_server.main()
    elif "--version" in sys.argv:
        from version import __version__
        print(__version__)
    elif "--smoke-test" in sys.argv:
        import json
        import platform_tools
        from version import __version__
        print(json.dumps({"version": __version__, "tools": [t[0] for t in platform_tools.TOOLS]}))
    elif "--confirm" in sys.argv:
        import json
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from i18n import tr
        data = json.load(sys.stdin)
        app = QApplication([])
        dialog = QMessageBox(QMessageBox.Icon.Question, "Mac Controller · " + data["title"], data["detail"])
        allow = dialog.addButton(tr("允许"), QMessageBox.ButtonRole.AcceptRole)
        deny = dialog.addButton(tr("拒绝"), QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(deny)
        dialog.exec()
        sys.exit(0 if dialog.clickedButton() is allow else 1)
    else:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        import app
        app.main()


if __name__ == "__main__":
    main()
