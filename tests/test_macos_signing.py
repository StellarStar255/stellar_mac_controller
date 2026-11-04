import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import plistlib
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('macos_signing', Path(__file__).resolve().parents[1]/'packaging/sign_macos.py')
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


class MacOSSigning(unittest.TestCase):
    def test_console_bundle_becomes_a_regular_dock_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)/'Example.app'
            (app/'Contents').mkdir(parents=True)
            path = app/'Contents/Info.plist'
            original = {'LSBackgroundOnly':True, 'LSUIElement':True,
                        'CFBundleIdentifier':'com.example.app', 'CFBundleShortVersionString':'0.3.1'}
            path.write_bytes(plistlib.dumps(original))
            signing.configure_gui_bundle(app)
            info = plistlib.loads(path.read_bytes())
            self.assertIs(info['LSBackgroundOnly'], False)
            self.assertIs(info['LSUIElement'], False)
            self.assertEqual(info['CFBundleIdentifier'], original['CFBundleIdentifier'])
            self.assertEqual(info['CFBundleShortVersionString'], original['CFBundleShortVersionString'])
    def test_notarytool_zero_exit_with_invalid_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.CompletedProcess([], 0, stdout=json.dumps({'status':'Invalid', 'id':'request-id'}))
            with patch.object(signing, 'run', return_value=result):
                with self.assertRaisesRegex(RuntimeError, 'Invalid'):
                    signing.notarize(Path('example.dmg'), 'profile', Path(tmp))

    def test_developer_id_and_hardened_runtime_are_required(self):
        for details in ('Signature=adhoc\nflags=runtime', 'Authority=Developer ID Application: Example'):
            with tempfile.TemporaryDirectory() as tmp:
                app = Path(tmp)/'Example.app'
                app.mkdir()
                with patch.object(signing, 'run', return_value=subprocess.CompletedProcess([], 0, stderr=details)):
                    with self.assertRaisesRegex(RuntimeError, 'hardened Developer ID'):
                        signing.sign_app(app, 'identity')

    def test_signing_cli_refuses_ad_hoc_identity(self):
        with patch('sys.argv', ['sign_macos.py', 'example.dmg', '--output', 'output', '--identity', '-']):
            with self.assertRaises(SystemExit) as error:
                signing.main()
            self.assertEqual(error.exception.code, 2)

    def test_pkg_builder_rejects_temporary_signed_payload(self):
        result = subprocess.CompletedProcess([], 0, stdout='', stderr='Signature=adhoc\nflags=runtime')
        with patch.object(signing, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'hardened Developer ID'):
                signing.package_signed_app(Path('Example.app'), Path('Example.pkg'))

    def test_designated_requirement_reads_both_output_streams(self):
        requirement = 'designated => anchor apple generic and identifier "com.example.app"'
        for stdout, stderr in ((requirement, 'Executable=/path/Example.app'), ('', requirement)):
            result = subprocess.CompletedProcess([], 0, stdout=stdout, stderr=stderr)
            with patch.object(signing, 'run', return_value=result):
                self.assertEqual(signing.designated_requirement(Path('Example.app')), requirement)

    def test_missing_designated_requirement_stops_packaging(self):
        result = subprocess.CompletedProcess([], 0, stdout='', stderr='Executable=/path/Example.app')
        with patch.object(signing, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'designated code requirement'):
                signing.designated_requirement(Path('Example.app'))
