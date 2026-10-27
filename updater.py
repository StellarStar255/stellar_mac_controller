"""Download release installers over TLS and verify their published SHA-256."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import ssl
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from version import REPOSITORY, __version__

API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES = f"https://github.com/{REPOSITORY}/releases"
MAX_DOWNLOAD = 1024 * 1024 * 1024


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise ValueError("不支持的版本号：" + value)
    return tuple(map(int, match.groups()))


def platform_key(system=None, machine=None):
    system, machine = system or sys.platform, (machine or platform.machine()).lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    os_name = {"darwin": "macos", "win32": "windows", "linux": "linux"}.get(system)
    if not os_name or not arch:
        raise ValueError("暂不提供此系统架构的安装包。")
    return f"{os_name}-{arch}"


def _open(url):
    import certifi
    if urlparse(url).scheme != "https":
        raise ValueError("更新只允许 HTTPS 下载。")
    return urlopen(Request(url, headers={"User-Agent": f"MacController/{__version__}"}),
                   timeout=45, context=ssl.create_default_context(cafile=certifi.where()))


def _json(url):
    with _open(url) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("更新元数据过大。")
    return json.loads(raw)


def _asset_url(url, tag):
    prefix = f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    if not url.startswith(prefix) or urlparse(url).query or urlparse(url).fragment:
        raise ValueError("安装包必须来自本项目的同一版本 Release。")
    return url


def check_update(current=__version__):
    release = _json(API)
    tag = release["tag_name"]
    if release.get("draft") or release.get("prerelease") or version_tuple(tag) <= version_tuple(current):
        return None
    manifest_asset = next((a for a in release.get("assets", []) if a["name"] == "update-manifest.json"), None)
    if not manifest_asset:
        raise ValueError("此版本的安装包尚未准备完成，请稍后重试。")
    manifest = _json(_asset_url(manifest_asset["browser_download_url"], tag))
    if manifest.get("version") != tag.lstrip("v"):
        raise ValueError("更新版本与清单不一致。")
    entry = manifest["platforms"].get(platform_key())
    if not entry:
        raise ValueError("此版本暂时没有适合本机架构的安装包。")
    entry = dict(entry)
    expected_suffix = {"darwin": ".pkg", "win32": ".exe", "linux": ".deb"}[sys.platform]
    if sys.platform == "linux" and ".local" in str(Path(sys.executable)):
        entry = dict(manifest["platforms"].get(platform_key() + "-portable", entry))
        entry["url"] = _asset_url(entry["url"], tag)
        expected_suffix = ".run"
    entry["url"] = _asset_url(entry["url"], tag)
    if not re.fullmatch(r"[a-f0-9]{64}", entry.get("sha256", "")):
        raise ValueError("更新清单缺少有效校验值。")
    if not isinstance(entry.get("size"), int) or not 0 < entry["size"] <= MAX_DOWNLOAD:
        raise ValueError("安装包大小无效。")
    if Path(entry["name"]).name != entry["name"] or not entry["name"].endswith(expected_suffix):
        raise ValueError("安装包文件名无效。")
    entry["version"] = manifest["version"]
    return entry


def download_update(entry):
    directory = Path(tempfile.mkdtemp(prefix="mac-controller-update-"))
    target = directory / entry["name"]
    digest, total = hashlib.sha256(), 0
    try:
        with _open(entry["url"]) as response, target.open("wb") as output:
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > MAX_DOWNLOAD:
                    raise ValueError("安装包超出大小限制。")
                output.write(block)
                digest.update(block)
        if total != entry["size"] or digest.hexdigest() != entry["sha256"]:
            raise ValueError("安装包校验失败，已取消安装。")
        return target
    except Exception:
        target.unlink(missing_ok=True)
        directory.rmdir()
        raise


def launch_installer(path):
    path = Path(path).resolve()
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen([str(path), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"])
    else:
        if path.suffix == ".deb":
            subprocess.Popen(["xdg-open", str(path)], start_new_session=True)
        else:
            subprocess.Popen(["sh", str(path), "--update"], start_new_session=True)
