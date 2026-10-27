"""生成可双击启动的「Mac 控制台.app」（放在本目录下）。运行：python3 make_app.py

App 本身只是一个启动脚本：用当前这个 Python 运行本目录的 app.py。
双击启动后，系统的「辅助功能 / 屏幕录制」权限会记在「Mac 控制台」这个 App 名下，和终端分开。
"""
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from app_icons import draw_icon, make_icns

HERE = Path(__file__).resolve().parent
APP = HERE / "Mac 控制台.app"
BUNDLE_ID = "com.stellar.maccontroller"
LOG = "$HOME/Library/Logs/MacController.log"

LAUNCHER = f"""#!/bin/zsh
# 从访达双击启动时 PATH 很短，这里补上 python / claude 所在目录
export PATH="{Path(sys.executable).parent}:/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# 双击启动时没有终端里的代理变量，claude 会直连被拒（403）；这里沿用系统设置里的 HTTPS 代理
if [[ -z "$https_proxy$HTTPS_PROXY" ]]; then
  px=$(scutil --proxy | awk '/HTTPSEnable/{{e=$3}} /HTTPSProxy/{{h=$3}} /HTTPSPort/{{p=$3}} END{{if (e==1 && h!="") print "http://" h ":" p}}')
  if [[ -n "$px" ]]; then
    export https_proxy="$px" http_proxy="$px" HTTPS_PROXY="$px" HTTP_PROXY="$px"
    export no_proxy="localhost,127.0.0.1,::1" NO_PROXY="localhost,127.0.0.1,::1"
  fi
fi
echo "[$(date '+%F %T')] 启动，代理：${{https_proxy:-无}}" >> "{LOG}"
cd "{HERE}" || exit 1
exec "{sys.executable}" app.py >> "{LOG}" 2>&1
"""



def main():
    if APP.exists():
        shutil.rmtree(APP)
    macos, res = APP / "Contents" / "MacOS", APP / "Contents" / "Resources"
    macos.mkdir(parents=True)
    res.mkdir()
    exe = macos / "MacController"
    exe.write_text(LAUNCHER)
    exe.chmod(0o755)
    make_icns(res / "AppIcon.icns")
    with open(APP / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({
            "CFBundleName": "Mac 控制台",
            "CFBundleDisplayName": "Mac 控制台",
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleExecutable": "MacController",
            "CFBundleIconFile": "AppIcon",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "1",
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "NSAppleEventsUsageDescription": "Mac 控制台需要控制其它程序来完成你交代的操作。",
        }, f)
    # 本地签名，让系统的权限记录稳定地认这个 App
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(APP)], check=True,
                   capture_output=True)
    subprocess.run(["touch", str(APP)])
    print(f"已生成：{APP}")
    print(f"日志：{os.path.expandvars(LOG)}")


if __name__ == "__main__":
    main()
