"""Explicit host-admin bootstrap. Existing settings/key survive reinstallation."""
import argparse
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess

def install(config,origins):
    if os.geteuid()!=0:raise SystemExit('Run on the physical host as root')
    source=Path(__file__).resolve().parent
    value=json.loads(Path(config).read_text())
    if not value.get('targets') or not value.get('host'):raise ValueError('Host and targets required')
    forbidden={'neofand.service','neofand'}
    for target in value['targets']:
        if forbidden.intersection(target.get('units',[])+target.get('start_units',[])):
            raise ValueError('The fan daemon must never be an update target')
        if not Path(target['destination']).is_absolute() or not Path(target['backup_root']).is_absolute():
            raise ValueError('Absolute deployment and backup paths required')
    for origin in origins:
        from urllib.parse import urlsplit
        parsed=urlsplit(origin)
        if parsed.scheme not in ('https','http') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise ValueError('Use exact browser origins, without a path')
    try:account=pwd.getpwnam('chassisdeck-updates')
    except KeyError:
        subprocess.run(['useradd','--system','--home-dir','/nonexistent','--shell','/usr/sbin/nologin','chassisdeck-updates'],check=True)
        account=pwd.getpwnam('chassisdeck-updates')
    dirs={'/opt/chassisdeck-updater':0o755,'/etc/chassisdeck-updater':0o750,
          '/var/lib/chassisdeck-updates':0o755,'/var/cache/chassisdeck-updates':0o700,
          '/var/lib/chassisdeck-update-api':0o755,'/var/lib/chassisdeck-update-api/run':0o755}
    for name,mode in dirs.items():
        p=Path(name)
        if p.is_symlink():raise ValueError('Refusing symlink directory')
        p.mkdir(parents=True,exist_ok=True);p.chmod(mode)
        api=name.startswith('/var/lib/chassisdeck-update-api')
        os.chown(p,account.pw_uid if api else 0,account.pw_gid if api or name=='/etc/chassisdeck-updater' else 0)
    for name in ('update_api.py','update_worker.py'):
        target=Path('/opt/chassisdeck-updater')/name
        if target.is_symlink():raise ValueError('Refusing symlink code')
        shutil.copyfile(source/name,target);target.chmod(0o644);os.chown(target,0,0)
    directory=Path('/etc/chassisdeck-updater');key=directory/'admin-token'
    if key.is_symlink():raise ValueError('Refusing symlink key')
    if not key.exists():
        fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as out:out.write(secrets.token_urlsafe(32)+'\n')
    key.chmod(0o600);os.chown(key,0,0)
    for name,data,mode,gid in [('api.json',{'origins':origins,'token_sha256':hashlib.sha256(key.read_text().strip().encode()).hexdigest()},0o640,account.pw_gid),('worker.json',value,0o600,0)]:
        p=directory/name
        if p.is_symlink():raise ValueError('Refusing symlink config')
        p.write_text(json.dumps(data,indent=2)+'\n');p.chmod(mode);os.chown(p,0,gid)
    settings=Path('/var/lib/chassisdeck-update-api/settings.json')
    if not settings.exists():
        settings.write_text('{"auto_enabled":false,"changed_at":0,"check_requested":0}\n')
        settings.chmod(0o644);os.chown(settings,account.pw_uid,account.pw_gid)
    for name in ('chassisdeck-update-api.service','chassisdeck-update-worker.service','chassisdeck-update-worker.timer'):
        shutil.copyfile(source/name,Path('/etc/systemd/system')/name)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','chassisdeck-update-api.service','chassisdeck-update-worker.timer'],check=True)
    subprocess.run(['systemctl','restart','chassisdeck-update-api.service'],check=True)
    print('Installed. Automatic updates retain their existing setting (off on first install). Admin key stays on the host.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--origin',action='append',required=True)
    args=parser.parse_args();install(args.config,args.origin)
