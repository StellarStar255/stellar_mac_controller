import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import updater
import backends
import runtime_support


class Updates(unittest.TestCase):
    def test_actual_release_manifest_selects_the_correct_installer(self):
        from version import __version__
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            suffixes = ['macos-arm64.pkg', 'macos-x64.pkg', 'windows-x64-setup.exe',
                        'linux-x64.deb', 'linux-x64.run']
            for suffix in suffixes:
                (root / f'MacController-{__version__}-{suffix}').write_bytes(b'package')
            subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'packaging/manifest.py'),tmp],check=True)
            manifest = json.loads((root/'update-manifest.json').read_text())
            tag = 'v'+__version__
            release = {'tag_name':tag,'assets':[{'name':'update-manifest.json',
                        'browser_download_url':f'{updater.RELEASES}/download/{tag}/update-manifest.json'}]}
            for system,key,suffix in [('darwin','macos-arm64','.pkg'),('darwin','macos-x64','.pkg'),
                                      ('win32','windows-x64','.exe'),('linux','linux-x64','.deb')]:
                with patch('updater._json',side_effect=[release,manifest]), patch('updater.platform_key',return_value=key), patch.object(updater.sys,'platform',system):
                    entry=updater.check_update(current='0.1.0')
                self.assertTrue(entry['name'].endswith(suffix))
                self.assertEqual(entry['size'],7)

    def test_system_commands_do_not_inherit_bundled_libraries(self):
        with patch.object(runtime_support.sys, 'frozen', True, create=True), patch.dict(
                runtime_support.os.environ, {'LD_LIBRARY_PATH':'/bundle', 'LD_LIBRARY_PATH_ORIG':'/system'}):
            self.assertEqual(runtime_support.external_env()['LD_LIBRARY_PATH'], '/system')
            self.assertEqual(runtime_support.os.environ['LD_LIBRARY_PATH'], '/bundle')

    def test_numeric_versions_and_supported_architectures(self):
        self.assertGreater(updater.version_tuple('v0.10.0'), updater.version_tuple('0.2.0'))
        for os_name, cpu, key in [('darwin','arm64','macos-arm64'),('darwin','x86_64','macos-x64'),
                                  ('win32','AMD64','windows-x64'),('linux','x86_64','linux-x64')]:
            self.assertEqual(updater.platform_key(os_name,cpu),key)
        with self.assertRaises(ValueError):
            updater.version_tuple('v0.3.0-rc1')

    def test_reject_foreign_and_wrong_release_downloads(self):
        for url in ('http://github.com/a', 'https://evil.example/setup.exe',
                    f'{updater.RELEASES}/download/v0.3.1/setup.exe'):
            with self.assertRaises(ValueError):
                updater._asset_url(url,'v0.3.0')

    def test_corrupt_download_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'download'
            folder.mkdir()
            with patch('updater.tempfile.mkdtemp',return_value=str(folder)), patch('updater._open',return_value=io.BytesIO(b'corrupt')):
                with self.assertRaises(ValueError):
                    updater.download_update({'name':'installer.pkg','url':'https://example.invalid',
                                             'size':7,'sha256':hashlib.sha256(b'correct').hexdigest()})
            self.assertFalse(folder.exists())

    def test_valid_download_and_frozen_mcp_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('updater.tempfile.mkdtemp',return_value=tmp), patch('updater._open',return_value=io.BytesIO(b'installer')):
                path=updater.download_update({'name':'setup.exe','url':'https://example.invalid',
                                             'size':9,'sha256':hashlib.sha256(b'installer').hexdigest()})
            self.assertEqual(path.read_bytes(),b'installer')
        with patch.object(backends.sys,'frozen',True,create=True):
            executable,args=backends.mcp_command()
            self.assertEqual(args,['--mcp'])
