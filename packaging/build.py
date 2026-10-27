"""Build native installers after PyInstaller; no local user files are included."""
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from version import __version__
from updater import platform_key


def run(args):
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def main():
    output = ROOT / 'release'
    output.mkdir(exist_ok=True)
    (ROOT / 'build').mkdir(exist_ok=True)
    if sys.platform == 'darwin':
        from make_app import make_icns
        make_icns(ROOT / 'build/AppIcon.icns')
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', 'MacController.spec'])
    if sys.platform == 'darwin':
        app = ROOT / 'dist/Mac Controller.app'
        run(['codesign', '--force', '--deep', '--sign', '-', app])
        pkgroot = ROOT / 'build/pkgroot'
        pkgroot.mkdir(exist_ok=True)
        shutil.copytree(app, pkgroot / app.name, symlinks=True, dirs_exist_ok=True)
        components = ROOT / 'build/components.plist'
        run(['pkgbuild', '--analyze', '--root', pkgroot, components])
        entries = plistlib.loads(components.read_bytes())
        for entry in entries:
            entry['BundleIsRelocatable'] = False
            entry['BundleOverwriteAction'] = 'upgrade'
        components.write_bytes(plistlib.dumps(entries))
        package = output / f'MacController-{__version__}-{platform_key()}.pkg'
        run(['pkgbuild', '--root', pkgroot, '--identifier', 'com.stellar.maccontroller',
             '--version', __version__, '--component-plist', components,
             '--install-location', '/Applications', package])
    elif sys.platform == 'win32':
        compiler = shutil.which('ISCC') or r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
        run([compiler, f'/DAppVersion={__version__}', ROOT / 'packaging/windows.iss'])
    else:
        archive = ROOT / 'build/linux-payload.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(ROOT / 'dist/MacController', arcname='MacController')
        package = output / f'MacController-{__version__}-{platform_key()}.run'
        with package.open('wb') as dest:
            dest.write((ROOT / 'packaging/linux-installer.sh').read_bytes())
            with archive.open('rb') as source:
                shutil.copyfileobj(source, dest)
        package.chmod(0o755)
        # Native double-click package for Debian/Ubuntu desktop software installers.
        debroot = ROOT / 'build/debroot'
        appdir = debroot / 'opt/stellar-mac-controller'
        shutil.copytree(ROOT / 'dist/MacController', appdir, symlinks=True, dirs_exist_ok=True)
        desktop = debroot / 'usr/share/applications'
        desktop.mkdir(parents=True, exist_ok=True)
        (desktop / 'stellar-mac-controller.desktop').write_text(
            '[Desktop Entry]\nType=Application\nName=Mac Controller\n'
            'Exec=/opt/stellar-mac-controller/MacController\nTerminal=false\nCategories=Utility;\n')
        control = debroot / 'DEBIAN'
        control.mkdir(exist_ok=True)
        (control / 'control').write_text(
            f'Package: stellar-mac-controller\nVersion: {__version__}\nArchitecture: amd64\n'
            'Maintainer: StellarStar255 <StellarStar255@users.noreply.github.com>\n'
            'Depends: libegl1, libopengl0, libxcb-cursor0, libxkbcommon-x11-0, libxcb-icccm4, '
            'libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-xinerama0, libxcb-shape0, '
            'libxcb-xfixes0, libxcb-sync1, libxcb-randr0, libxcb-xkb1, libxcb-util1, libx11-xcb1, '
            'libxrender1, libxi6, libsm6, libice6, xclip, wmctrl, xdotool\n'
            'Description: Desktop AI assistant with local computer tools\n')
        run(['dpkg-deb', '--root-owner-group', '--build', debroot,
             output / f'MacController-{__version__}-{platform_key()}.deb'])


if __name__ == '__main__':
    main()
