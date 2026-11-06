"""Build one versioned application bundle from a clean Git checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = 'akhilv1/hardware-dashboard'

def build(version, output):
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?', version):
        raise ValueError('Use a version tag such as v0.1.0')
    git = lambda *args: subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()
    if git('status', '--porcelain'):
        raise ValueError('Release builds require a clean checkout')
    commit = git('rev-parse', 'HEAD')
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / ('chassisdeck-' + version); stage.mkdir()
        payload = stage / 'payload'; payload.mkdir()
        tracked = git('ls-files', 'dashboard/assets').splitlines()
        for name in tracked:
            source = ROOT / name
            if source.is_symlink(): raise ValueError('Symlink asset is not supported')
            target = payload / Path(name).relative_to('dashboard')
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
        (payload / 'macpro').mkdir(); (payload / 'linux').mkdir(); (payload / 'p620').mkdir()
        shutil.copyfile(ROOT/'dashboard/index.html', payload/'macpro/index.html')
        subprocess.run(['python3', str(ROOT/'dashboard/linux/build_p620.py'),
                        str(ROOT/'dashboard/index.html'), str(payload/'linux/index.html')], check=True)
        for name in ('p620.js','p620.css','proxmox.js'):
            shutil.copyfile(ROOT/'dashboard/linux'/name, payload/'assets'/name)
        library=(payload/'assets/gpu-library/index.html').read_text()
        (payload/'p620/gpu-library.html').write_text(library.replace('<html lang="en">','<html lang="en" data-platform="lenovo-p620">',1))
        metadata=dict(repository=REPOSITORY, version=version, commit=commit, branch=version,
                      pr_number=None, dirty=False)
        (payload/'assets/build-info.json').write_text(json.dumps(metadata,indent=2)+'\n')
        scripts = {Path(name).name:ROOT/name for name in git('ls-files','dashboard').splitlines()
                   if Path(name).parent==Path('dashboard') and name.endswith('.py') and not Path(name).name.startswith('test_')}
        scripts.update({name:ROOT/'dashboard/linux'/name for name in ('linux_api.py','linux_telemetry.py')})
        scripts['proxmox_collect.py']=ROOT/'dashboard/lxc/proxmox_collect.py'
        (payload/'scripts').mkdir()
        for name,path in scripts.items():shutil.copyfile(path,payload/'scripts'/name)
        assets={str(p.relative_to(payload)):str(p.relative_to(payload)) for p in (payload/'assets').rglob('*') if p.is_file()}
        common=('system_events.py','storage_collect.py','storage_topology.py','storage_breakdown.py','storage_index.py','portainer_collect.py','export_history.py')
        mapping=lambda names:{name:'scripts/'+name for name in names}
        mac={**assets, 'index.html':'macpro/index.html', **mapping(('memory_api.py',)+common)}
        linux={**assets, 'index.html':'linux/index.html', **mapping(('linux_api.py','linux_telemetry.py')+common)}
        p620={**linux,'assets/gpu-library/index.html':'p620/gpu-library.html'}
        lxc={**{'www/'+key:value for key,value in assets.items()},'www/index.html':'linux/index.html','linux_api.py':'scripts/linux_api.py'}
        host=mapping(('linux_telemetry.py','system_events.py','storage_collect.py','storage_topology.py','proxmox_collect.py','export_history.py'))
        (payload/'updater').mkdir()
        updater={}
        for name in ('update_api.py','update_worker.py'):
            shutil.copyfile(ROOT/'dashboard/updater'/name,payload/'updater'/name)
            updater[name]='updater/'+name
        hashes={str(p.relative_to(payload)):hashlib.sha256(p.read_bytes()).hexdigest() for p in payload.rglob('*') if p.is_file()}
        manifest={**metadata,'files':hashes,'profiles':dict(updater=updater,macpro=mac,linux=linux,p620=p620,lxc=lxc,**{'proxmox-host':host})}
        (stage/'RELEASE.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
        shutil.copyfile(ROOT/'tools/install-release.py',stage/'install-release.py')
        shutil.copyfile(ROOT/'docs/RELEASES.md',stage/'README.md')
        shutil.copyfile(ROOT/'LICENCE',stage/'LICENCE')
        archive=output/(stage.name+'.tar.gz')
        # Normalize ownership and timestamps; only tracked source enters the payload.
        def normalize(info):
            info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
            info.mode=0o755 if info.isdir() else 0o644
            return info
        with tarfile.open(archive,'w:gz') as tar:tar.add(stage,arcname=stage.name,filter=normalize)
        checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
        (output/'SHA256SUMS').write_text(checksum+'  '+archive.name+'\n')
        (output/'release.json').write_text(json.dumps(metadata,indent=2)+'\n')
        print(archive);print(checksum)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('version');parser.add_argument('output')
    args=parser.parse_args();build(args.version,args.output)
