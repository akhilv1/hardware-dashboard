"""Check shared and generated frontend JavaScript without hardware or a daemon."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
for path in (root / 'dashboard').rglob('*.js'):
    subprocess.run(['node', '--check', str(path)], check=True)
with tempfile.TemporaryDirectory() as tmp:
    generated = Path(tmp) / 'linux.html'
    subprocess.run(['python3', str(root / 'dashboard/linux/build_p620.py'),
                    str(root / 'dashboard/index.html'), str(generated)], check=True)
    for page in (root / 'dashboard/index.html', generated):
        for attrs, code in re.findall(r'<script([^>]*)>(.*?)</script>', page.read_text(), re.S):
            if not code.strip() or re.search(r'type=[\"\'](?:application/ld\+json|application/json)', attrs):
                continue
            subprocess.run(['node', '--check'], input=code, text=True, check=True)
print('Shared and generated frontend syntax passed')
