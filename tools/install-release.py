"""Install a verified release into an existing deployment; never change services/config/data."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import time

def safe_path(root, relative):
    parts=PurePosixPath(relative)
    if parts.is_absolute() or not parts.parts or any(p in ('.','..') for p in parts.parts):
        raise ValueError('Unsafe release path')
    target=root.joinpath(*parts.parts)
    for path in (target,*target.parents):
        if path==root.parent:break
        if path.is_symlink():raise ValueError('Refusing symlink: '+str(path))
    return target

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def atomic_copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    stat=target.stat() if target.exists() else None
    fd,tmp=tempfile.mkstemp(prefix='.chassisdeck-',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as output:
            output.write(source.read_bytes());output.flush();os.fsync(output.fileno())
        os.chmod(tmp,(stat.st_mode & 0o777) if stat else 0o644)
        if stat and os.geteuid()==0:os.chown(tmp,stat.st_uid,stat.st_gid)
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def install(bundle,destination,profile,backup_root):
    bundle=Path(bundle).resolve();destination=Path(destination).absolute();backup_root=Path(backup_root).absolute()
    if destination.is_symlink() or not destination.is_dir():raise ValueError('Destination must be an existing real directory')
    if backup_root==destination or destination in backup_root.parents:raise ValueError('Backups must be outside the deployment')
    manifest=json.loads((bundle/'RELEASE.json').read_text());files=manifest['files'];mapping=manifest['profiles'][profile]
    # Verify every selected payload before writing any live file.
    targets={}
    for relative,source in mapping.items():
        src=safe_path(bundle/'payload',source);target=safe_path(destination,relative)
        if not src.is_file() or digest(src)!=files[source]:raise ValueError('Payload checksum mismatch: '+source)
        if target.exists() and not target.is_file():raise ValueError('Destination is not a file: '+relative)
        targets[relative]=(src,target)
    lock=safe_path(destination,'.chassisdeck-release.json')
    if lock.exists():
        previous=json.loads(lock.read_text())
        for relative,expected in previous.get('installed_files',{}).items():
            path=safe_path(destination,relative)
            if not path.is_file() or digest(path)!=expected:raise ValueError('Installed release was modified: '+relative)
    for path in (backup_root,*backup_root.parents):
        if path.is_symlink():raise ValueError('Backup path contains a symlink')
    backup_root.mkdir(parents=True,exist_ok=True)
    backup=Path(tempfile.mkdtemp(prefix=manifest['version']+'-',dir=backup_root))
    # Back up only code being replaced, never telemetry, credentials, or host config.
    rollback={}
    for relative,(_,target) in targets.items():
        if target.exists():
            saved=safe_path(backup/'files',relative);saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
            rollback[relative]=digest(saved)
        else:rollback[relative]=None
    if lock.exists():shutil.copy2(lock,backup/'previous-release.json')
    (backup/'rollback.json').write_text(json.dumps({'destination':str(destination),'files':rollback},indent=2)+'\n')
    try:
        for src,target in targets.values():atomic_copy(src,target)
        pin={key:manifest[key] for key in ('repository','version','commit')}
        pin.update(profile=profile,installed_at=time.time(),backup=str(backup),
                   installed_files={name:files[mapping[name]] for name in targets})
        temp=backup/'new-release.json';temp.write_text(json.dumps(pin,indent=2)+'\n');atomic_copy(temp,lock)
    except Exception:
        # Undo a partial application before propagating an I/O failure.
        for relative,expected in rollback.items():
            target=safe_path(destination,relative)
            if expected:atomic_copy(backup/'files'/relative,target)
            elif target.exists():target.unlink()
        if (backup/'previous-release.json').exists():atomic_copy(backup/'previous-release.json',lock)
        elif lock.exists():lock.unlink()
        raise
    print(json.dumps({'version':pin['version'],'profile':profile,'backup':str(backup),'files':len(targets)}))
    return backup

def restore(backup,destination):
    backup=Path(backup).resolve();destination=Path(destination).absolute()
    plan=json.loads((backup/'rollback.json').read_text())
    if str(destination)!=plan['destination']:raise ValueError('Rollback destination mismatch')
    lock=safe_path(destination,'.chassisdeck-release.json')
    if lock.exists():
        current=json.loads(lock.read_text())
        if current.get('backup')!=str(backup):raise ValueError('Backup is not the current installation rollback')
        for name,expected in current.get('installed_files',{}).items():
            target=safe_path(destination,name)
            if not target.is_file() or digest(target)!=expected:raise ValueError('Current files modified; inspect before rollback')
    for name,expected in plan['files'].items():
        safe_path(destination,name)
        if expected and digest(safe_path(backup/'files',name))!=expected:raise ValueError('Backup checksum mismatch')
    for name,expected in plan['files'].items():
        target=safe_path(destination,name)
        if expected:atomic_copy(backup/'files'/name,target)
        elif target.exists():target.unlink()
    if (backup/'previous-release.json').exists():atomic_copy(backup/'previous-release.json',lock)
    elif lock.exists():lock.unlink()
    print('Restored '+str(backup))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--destination',required=True)
    parser.add_argument('--bundle',default=str(Path(__file__).resolve().parent))
    parser.add_argument('--profile',choices=['macpro','linux','p620','lxc','proxmox-host','updater'])
    parser.add_argument('--backup-root');parser.add_argument('--restore')
    args=parser.parse_args()
    if args.restore:restore(args.restore,args.destination)
    else:
        if not args.profile or not args.backup_root:parser.error('--profile and --backup-root are required')
        install(args.bundle,args.destination,args.profile,args.backup_root)
