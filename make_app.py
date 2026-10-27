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

from PIL import Image, ImageDraw

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


def draw_icon(size):
    s = size / 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg = Image.new("RGBA", (size, size))
    top, bottom = (72, 118, 255), (138, 70, 230)
    px = bg.load()
    for y in range(size):
        t = y / max(1, size - 1)
        c = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(size):
            px[x, y] = c
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([100 * s, 100 * s, 924 * s, 924 * s], radius=190 * s, fill=255)
    img.paste(bg, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # 一个窗口
    d.rounded_rectangle([230 * s, 270 * s, 800 * s, 700 * s], radius=48 * s, outline="white", width=max(1, round(40 * s)))
    d.line([250 * s, 370 * s, 780 * s, 370 * s], fill="white", width=max(1, round(34 * s)))
    for i, x in enumerate((300, 360, 420)):
        d.ellipse([(x - 18) * s, 302 * s, (x + 18) * s, 338 * s], fill="white")
    # 一个鼠标指针
    arrow = [(560, 470), (560, 820), (640, 740), (700, 870), (760, 845), (700, 715), (810, 715)]
    d.polygon([(x * s, y * s) for x, y in arrow], fill="white", outline=(60, 40, 140))
    return img


def make_icns(dest):
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        big = draw_icon(1024)
        for pt in (16, 32, 128, 256, 512):
            big.resize((pt, pt), Image.LANCZOS).save(iconset / f"icon_{pt}x{pt}.png")
            big.resize((pt * 2, pt * 2), Image.LANCZOS).save(iconset / f"icon_{pt}x{pt}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)], check=True)


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
