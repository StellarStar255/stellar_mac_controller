# Build on each target OS; native libraries cannot be cross-compiled.
from pathlib import Path
import sys
from version import __version__

root = Path(SPECPATH)
mac = sys.platform == 'darwin'
excludes = (['desktop_tools', 'desktop_common', 'pyautogui', 'pywinauto', 'pygetwindow', 'mss'] if mac
            else ['mac_tools', 'Quartz', 'ApplicationServices', 'AppKit', 'Foundation', 'objc'])
a = Analysis([str(root / 'launcher.py')], pathex=[str(root)],
             datas=[(str(root / 'assets'), 'assets')], binaries=[],
             hiddenimports=['mcp_server', 'app', 'platform_tools', 'anthropic', 'certifi'],
             hookspath=[], runtime_hooks=[], excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MacController',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, argv_emulation=False, target_arch=None,
          icon=str(root / 'build/AppIcon.ico') if sys.platform == 'win32' else None,
          codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MacController')
if mac:
    app = BUNDLE(coll, name='Mac Controller.app', icon=str(root / 'build/AppIcon.icns'),
                 bundle_identifier='com.stellar.maccontroller', version=__version__,
                 info_plist={'NSHighResolutionCapable': True,
                             # Keep stdio for MCP, but launch the GUI as a regular Dock app.
                             'LSBackgroundOnly': False,
                             'LSUIElement': False,
                             'NSAppleEventsUsageDescription': '控制其它程序来完成用户交代的操作。',
                             'NSScreenCaptureUsageDescription': '查看屏幕以操作用户指定的程序。',
                             'LSMinimumSystemVersion': '12.0'})
