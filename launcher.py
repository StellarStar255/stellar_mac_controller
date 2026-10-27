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
        data = json.load(sys.stdin)
        app = QApplication([])
        answer = QMessageBox.question(None, "Mac Controller · " + data["title"], data["detail"],
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        sys.exit(0 if answer == QMessageBox.StandardButton.Yes else 1)
    else:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        import app
        app.main()


if __name__ == "__main__":
    main()
