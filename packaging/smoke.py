"""Exercise the actual frozen GUI and its stdio MCP entry point."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from version import __version__

exe = ROOT / ('dist/Mac Controller.app/Contents/MacOS/MacController' if sys.platform == 'darwin'
              else 'dist/MacController/MacController.exe' if sys.platform == 'win32'
              else 'dist/MacController/MacController')
with tempfile.TemporaryDirectory() as tmp:
    env = {**os.environ, 'MAC_CTRL_DATA_DIR': tmp, 'MAC_CTRL_WORKDIR': tmp, 'MACCTRL_GUI_SMOKE': '1',
           'MAC_CTRL_LANGUAGE': 'en', 'MACCTRL_LANGUAGE_TEST': '1'}
    r = subprocess.run([str(exe), '--smoke-test'], capture_output=True, text=True, encoding='utf-8', env=env, timeout=60, check=True)
    assert json.loads(r.stdout)['version'] == __version__
    messages = [
        {'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},
        {'jsonrpc':'2.0','id':2,'method':'tools/list'},
        {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'note_write','arguments':{'name':'smoke','content':'ok'}}},
        {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'note_read','arguments':{'name':'smoke'}}},
    ]
    r = subprocess.run([str(exe), '--mcp'], input='\n'.join(map(json.dumps,messages))+'\n', capture_output=True,
                       text=True, encoding='utf-8', env=env, timeout=60, check=True)
    replies = [json.loads(line) for line in r.stdout.splitlines()]
    assert len(replies) == 4, r.stdout
    assert 'result' in replies[1], replies
    assert replies[1]['result']['tools']
    assert not replies[2]['result']['isError']
    assert 'ok' in replies[3]['result']['content'][0]['text']
    if sys.platform == 'linux':
        for library in (ROOT/'dist').rglob('libqxcb.so'):
            dependencies = subprocess.check_output(['ldd',str(library)],text=True)
            assert 'not found' not in dependencies, dependencies
    subprocess.run([str(exe)], env=env, timeout=60, check=True)
    if sys.platform == 'linux':
        deb = next((ROOT/'release').glob('*.deb'))
        subprocess.run(['dpkg-deb','-x',str(deb),str(Path(tmp)/'deb')],check=True)
        subprocess.run([str(Path(tmp)/'deb/opt/stellar-mac-controller/MacController'),'--smoke-test'],
                       env=env,timeout=60,check=True)
        install_env = {**env, 'HOME': tmp, 'XDG_DATA_HOME': str(Path(tmp)/'data')}
        installer = next((ROOT/'release').glob('*.run'))
        subprocess.run(['sh',str(installer)], env=install_env, timeout=60, check=True)
        installed = Path(tmp)/'data/stellar-mac-controller/MacController'
        assert installed.exists()
        # Installing twice exercises the update/replace path without touching user data.
        subprocess.run(['sh',str(installer)], env=install_env, timeout=60, check=True)
        subprocess.run([str(installed),'--smoke-test'], env=install_env, timeout=60, check=True)
    if sys.platform == 'darwin':
        package = next((ROOT/'release').glob('*.pkg'))
        subprocess.run(['pkgutil','--expand',str(package),str(Path(tmp)/'expanded')], check=True)
    if sys.platform == 'win32':
        installer = next((ROOT/'release').glob('*.exe'))
        install_dir = Path(tmp)/'installed'
        subprocess.run([str(installer),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',f'/DIR={install_dir}'], check=True, timeout=90)
        subprocess.run([str(install_dir/'MacController.exe'),'--smoke-test'], check=True, env=env, timeout=60)
print('Frozen GUI, MCP and installer smoke tests passed.')
