"""Shared application artwork for native packages and desktop windows."""
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw


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

