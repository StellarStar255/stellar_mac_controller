"""Finalize existing macOS DMGs using a local Developer ID and notary profile.

No private keys or passwords are exported. Both the app and the DMG receive
notarization tickets. Input images are never modified; publish outputs only
after all signature, ticket and Gatekeeper checks succeed.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENTITLEMENTS = ROOT / 'packaging/entitlements.plist'
MACHO = {bytes.fromhex(value) for value in (
    'feedface', 'cefaedfe', 'feedfacf', 'cffaedfe',
    'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}


def run(args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def notarize(path, profile, records):
    print(f'Submitting for Apple notarization: {path.name}', flush=True)
    result = run(['xcrun', 'notarytool', 'submit', path, '--keychain-profile', profile,
                  '--wait', '--timeout', '20m', '--output-format', 'json'],
                 capture_output=True, text=True)
    reply = json.loads(result.stdout)
    (records / f'{path.name}.json').write_text(json.dumps(reply, indent=2)+'\n')
    if reply.get('status') != 'Accepted':
        raise RuntimeError(f'Apple notarization failed: {reply.get("status")}; request {reply.get("id")}')
    print(f'Apple accepted: {path.name}', flush=True)


def sign_app(app, identity):
    targets = []
    for path in app.rglob('*'):
        if path.is_symlink():
            continue
        if path.is_file():
            with path.open('rb') as source:
                if source.read(4) in MACHO:
                    targets.append(path)
        elif path.suffix in ('.framework', '.app', '.xpc'):
            targets.append(path)
    targets.sort(key=lambda path: len(path.parts), reverse=True)
    targets.append(app)
    print(f'Signing {len(targets)} native binaries and bundles', flush=True)
    for path in targets:
        run(['codesign', '--force', '--timestamp', '--options', 'runtime',
             '--entitlements', ENTITLEMENTS, '--sign', identity, path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    run(['codesign', '--verify', '--deep', '--strict', app])
    details = run(['codesign', '-dvvv', app], capture_output=True, text=True).stderr
    if 'Authority=Developer ID Application:' not in details or 'runtime' not in details:
        raise RuntimeError('App does not have a hardened Developer ID signature')


def configure_gui_bundle(app):
    """Override PyInstaller's console-mode background default before signing."""
    path = app/'Contents/Info.plist'
    info = plistlib.loads(path.read_bytes())
    info['LSBackgroundOnly'] = False
    info['LSUIElement'] = False
    path.write_bytes(plistlib.dumps(info))
    return info


def verify_distribution_app(app):
    run(['codesign', '--verify', '--deep', '--strict', app])
    details = run(['codesign', '-dvvv', app], capture_output=True, text=True).stderr
    if 'Authority=Developer ID Application:' not in details or 'runtime' not in details:
        raise RuntimeError('Refusing to package an app without a hardened Developer ID signature')
    run(['xcrun', 'stapler', 'validate', app])
    run(['spctl', '--assess', '--type', 'execute', '--verbose=2', app])


def package_signed_app(app, target):
    """PKG updates must install the same signed app identity as DMG installs."""
    verify_distribution_app(app)
    info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
    requirement = designated_requirement(app)
    with tempfile.TemporaryDirectory(prefix='mac-controller-pkg-') as tmp:
        root = Path(tmp)
        payload = root/'payload'
        payload.mkdir()
        # ditto preserves resource forks, extended attributes and stapled tickets.
        run(['ditto', app, payload/app.name])
        components = root/'components.plist'
        run(['pkgbuild', '--analyze', '--root', payload, components])
        entries = plistlib.loads(components.read_bytes())
        for entry in entries:
            entry['BundleIsRelocatable'] = False
            entry['BundleOverwriteAction'] = 'upgrade'
        components.write_bytes(plistlib.dumps(entries))
        run(['pkgbuild', '--root', payload, '--identifier', info['CFBundleIdentifier'],
             '--version', info['CFBundleShortVersionString'], '--component-plist', components,
             '--install-location', '/Applications', target])
        expanded = root/'expanded'
        run(['pkgutil', '--expand-full', target, expanded])
        installed = list(expanded.rglob(app.name))
        if len(installed) != 1:
            raise RuntimeError('PKG must contain exactly one controller application')
        verify_distribution_app(installed[0])
        if designated_requirement(installed[0]) != requirement:
            raise RuntimeError('PKG payload changed the app signing identity')
    print(f'PKG payload verified: same signed, notarized app as DMG: {target}', flush=True)


def designated_requirement(app):
    result = run(['codesign', '-d', '-r-', app], capture_output=True, text=True)
    lines = [line.strip() for line in (result.stdout + '\n' + result.stderr).splitlines()
             if line.strip().startswith('designated =>')]
    if len(lines) != 1:
        raise RuntimeError('Unable to read the app designated code requirement')
    return lines[0]


def repackage_signed_image(image, output):
    """Repair an existing release PKG without re-signing or changing its DMG."""
    run(['codesign', '--verify', '--strict', image])
    run(['xcrun', 'stapler', 'validate', image])
    with tempfile.TemporaryDirectory(prefix='mac-controller-repackage-') as tmp:
        mount = Path(tmp)/'mounted'
        run(['hdiutil', 'attach', image, '-readonly', '-nobrowse', '-mountpoint', mount])
        try:
            app = mount/'Mac Controller.app'
            info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
            if not image.name.startswith(f"MacController-{info['CFBundleShortVersionString']}-macos-"):
                raise ValueError('DMG filename and app version differ')
            package_signed_app(app, output/(image.stem+'.pkg'))
        finally:
            run(['hdiutil', 'detach', mount])


def finalize(image, output, identity, profile, records):
    with tempfile.TemporaryDirectory(prefix='mac-controller-sign-') as tmp:
        root = Path(tmp)
        mount = root/'mounted'
        run(['hdiutil', 'attach', image, '-readonly', '-nobrowse', '-mountpoint', mount])
        stage = root/'stage'
        stage.mkdir()
        try:
            app = stage/'Mac Controller.app'
            shutil.copytree(mount/app.name, app, symlinks=True)
        finally:
            run(['hdiutil', 'detach', mount])
        info = configure_gui_bundle(app)
        version = info['CFBundleShortVersionString']
        if not image.name.startswith(f'MacController-{version}-macos-'):
            raise ValueError('DMG filename and app version differ')
        sign_app(app, identity)
        archive = root/f'{image.stem}.app.zip'
        run(['ditto', '-c', '-k', '--keepParent', app, archive])
        notarize(archive, profile, records)
        run(['xcrun', 'stapler', 'staple', app])
        run(['xcrun', 'stapler', 'validate', app])
        run(['spctl', '--assess', '--type', 'execute', '--verbose=2', app])
        package_signed_app(app, output/(image.stem+'.pkg'))
        (stage/'Applications').symlink_to('/Applications', target_is_directory=True)
        (stage/'Install - 安装.txt').write_text(
            'Quit the old app, drag Mac Controller.app into Applications, then launch it there.\n'
            '请先退出旧程序，将 Mac Controller.app 拖入 Applications，再从应用程序目录启动。\n', encoding='utf-8')
        target = output/image.name
        run(['hdiutil', 'create', '-volname', 'Mac Controller', '-srcfolder', stage,
             '-format', 'UDZO', '-fs', 'HFS+', '-ov', target])
        run(['codesign', '--force', '--timestamp', '--sign', identity, target])
        notarize(target, profile, records)
        run(['xcrun', 'stapler', 'staple', target])
        run(['xcrun', 'stapler', 'validate', target])
        run(['codesign', '--verify', '--strict', target])
        run(['spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature',
             '--verbose=2', target])
        print(f'Signed, notarized and stapled: {target}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--identity', default=os.environ.get('MACOS_SIGN_IDENTITY'))
    parser.add_argument('--profile', default=os.environ.get('NOTARY_PROFILE', 'stellar-notary'))
    parser.add_argument('--package-only', action='store_true',
                        help='Build verified PKGs from already signed and notarized DMGs; leave DMGs unchanged')
    args = parser.parse_args()
    if not args.package_only and (not args.identity or args.identity == '-'):
        parser.error('A Developer ID Application identity is required; ad-hoc signing is not allowed')
    args.output.mkdir(parents=True, exist_ok=True)
    records = ROOT/'build/notary'
    records.mkdir(parents=True, exist_ok=True)
    for image in args.images:
        if args.package_only:
            repackage_signed_image(image.resolve(), args.output.resolve())
            continue
        if image.resolve() == (args.output/image.name).resolve():
            parser.error('Input and output must be different paths')
        finalize(image.resolve(), args.output.resolve(), args.identity, args.profile, records)


if __name__ == '__main__':
    main()
