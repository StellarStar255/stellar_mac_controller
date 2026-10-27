"""Generate update manifest and SHA256SUMS from the actual release artifacts."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from version import __version__, REPOSITORY

folder = Path(sys.argv[1] if len(sys.argv) > 1 else 'release')
platforms = {}
lines = []
for path in sorted(folder.iterdir()):
    match = re.fullmatch(rf'MacController-{re.escape(__version__)}-(macos|windows|linux)-(arm64|x64)(?:-setup)?\.(pkg|dmg|exe|run|deb)', path.name)
    if not match:
        continue
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    key = f'{match[1]}-{match[2]}'
    if match[3] == 'run':
        key += '-portable'
    elif match[3] == 'dmg':
        key += '-disk-image'
    platforms[key] = {'name': path.name, 'sha256': digest, 'size': path.stat().st_size,
                      'url': f'https://github.com/{REPOSITORY}/releases/download/v{__version__}/{path.name}'}
    lines.append(f'{digest}  {path.name}')
required = {'macos-arm64', 'macos-x64', 'windows-x64', 'linux-x64'}
if not required.issubset(platforms):
    raise SystemExit(f'Missing installers: {required - platforms.keys()}')
(folder / 'update-manifest.json').write_text(json.dumps({'version': __version__, 'platforms': platforms}, indent=2)+'\n')
(folder / 'SHA256SUMS').write_text('\n'.join(lines)+'\n')
