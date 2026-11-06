"""Write deployment metadata for this checkout; never changes running services."""
import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('destination', type=Path)
parser.add_argument('--repository', default='akhilv1/hardware-dashboard')
parser.add_argument('--pr-number', type=int)
args = parser.parse_args()
if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
    parser.error('repository must be OWNER/NAME')
def git(*values):
    return subprocess.check_output(['git', '-C', str(root), *values], text=True).strip()
data = dict(repository=args.repository, commit=git('rev-parse', 'HEAD'),
            branch=git('branch', '--show-current') or 'detached', pr_number=args.pr_number,
            dirty=bool(git('status', '--porcelain', '--untracked-files=no')),
            built_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
args.destination.parent.mkdir(parents=True, exist_ok=True)
args.destination.write_text(json.dumps(data, indent=2) + '\n')
