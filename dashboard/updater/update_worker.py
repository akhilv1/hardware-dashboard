"""Root-owned release worker. UI settings contain no commands, URLs or paths."""
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import urllib.parse
import shutil

REPO='akhilv1/hardware-dashboard'
CONFIG=Path('/etc/chassisdeck-updater/worker.json')
STATE=Path('/var/lib/chassisdeck-updates')
SETTINGS=Path('/var/lib/chassisdeck-update-api/settings.json')
CACHE=Path('/var/cache/chassisdeck-updates')

def version(value):
    match=re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)',str(value))
    if not match:raise ValueError('Stable version tag required')
    return tuple(map(int,match.groups()))

def read(path,default):
    try:
        if path.is_symlink() or path.stat().st_size>262144:return default
        return json.loads(path.read_text())
    except (OSError,ValueError):return default

def save(status):
    fd,name=tempfile.mkstemp(prefix='.status-',dir=STATE)
    try:
        with os.fdopen(fd,'w') as out:json.dump(status,out);out.flush();os.fsync(out.fileno())
        os.chmod(name,0o644);os.replace(name,STATE/'status.json')
    finally:
        if os.path.exists(name):os.unlink(name)

def command(args,timeout=180):
    result=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,timeout=timeout,check=True)
    return result.stdout

def target_command(target,args,timeout=180):
    if target.get('ctid'):args=['pct','exec',str(target['ctid']),'--']+args
    return command(args,timeout)

def pin(target):
    if target.get('ctid'):
        return json.loads(target_command(target,['cat',target['destination']+'/.chassisdeck-release.json']))
    return read(Path(target['destination'])/'.chassisdeck-release.json',{})

DOWNLOAD_HOSTS=('api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com')
class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed=urllib.parse.urlparse(newurl)
        if parsed.scheme!='https' or parsed.hostname not in DOWNLOAD_HOSTS:
            raise ValueError('Unexpected release redirect')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(url,limit,destination=None):
    request=urllib.request.Request(url,headers={'User-Agent':'ChassisDeck-updater','Accept':'application/vnd.github+json'})
    started=time.monotonic();total=0;chunks=[]
    with urllib.request.build_opener(ReleaseRedirect()).open(request,timeout=30) as response:
        final=urllib.parse.urlparse(response.url)
        if final.scheme!='https' or final.hostname not in ('api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'):
            raise ValueError('Unexpected release download host')
        out=open(destination,'wb') if destination else None
        try:
            while chunk:=response.read(262144):
                total+=len(chunk)
                if total>limit or time.monotonic()-started>300:raise ValueError('Download limit exceeded')
                if out:out.write(chunk)
                else:chunks.append(chunk)
        finally:
            if out:out.close()
    return b''.join(chunks)

def latest():
    data=json.loads(fetch(f'https://api.github.com/repos/{REPO}/releases/latest',262144))
    tag=data['tag_name'];version(tag)
    if data.get('draft') or data.get('prerelease'):raise ValueError('Stable published release required')
    expected={f'chassisdeck-{tag}.tar.gz','SHA256SUMS','release.json'}
    for name in expected:
        matches=[a for a in data.get('assets',[]) if a.get('name')==name]
        url=f'https://github.com/{REPO}/releases/download/{tag}/{name}'
        if len(matches)!=1 or matches[0].get('browser_download_url')!=url:raise ValueError('Missing canonical release asset')
    return tag

def unpack(archive,destination,tag):
    prefix='chassisdeck-'+tag
    with tarfile.open(archive,'r:gz') as tar:
        members=tar.getmembers()
        if len(members)>5000 or sum(m.size for m in members)>600*1024*1024:raise ValueError('Archive limits exceeded')
        names=set()
        for item in members:
            p=PurePosixPath(item.name)
            if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!=prefix or item.name in names:
                raise ValueError('Unsafe archive path')
            if not (item.isfile() or item.isdir()):raise ValueError('Archive links/devices are not allowed')
            names.add(item.name)
        for item in members:
            path=destination.joinpath(*PurePosixPath(item.name).parts)
            if item.isdir():path.mkdir(parents=True,exist_ok=True)
            else:
                path.parent.mkdir(parents=True,exist_ok=True)
                with tar.extractfile(item) as src,open(path,'xb') as out:
                    while chunk:=src.read(262144):out.write(chunk)
                path.chmod(0o644)
    return destination/prefix

def download_payload(tag,folder):
    name=f'chassisdeck-{tag}.tar.gz'
    base=f'https://github.com/{REPO}/releases/download/{tag}/'
    sums=fetch(base+'SHA256SUMS',65536).decode().splitlines()
    expected=[line.split()[0] for line in sums if len(line.split())==2 and line.split()[1]==name]
    if len(expected)!=1 or not re.fullmatch('[a-f0-9]{64}',expected[0]):raise ValueError('Missing checksum')
    archive=folder/name;fetch(base+name,300*1024*1024,archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected[0]:raise ValueError('Release checksum mismatch')
    metadata=json.loads(fetch(base+'release.json',65536))
    bundle=unpack(archive,folder,tag);manifest=json.loads((bundle/'RELEASE.json').read_text())
    if (manifest.get('version')!=tag or manifest.get('repository')!=REPO or
        manifest.get('commit')!=metadata.get('commit') or not re.fullmatch('[a-f0-9]{40}',manifest.get('commit',''))):
        raise ValueError('Release identity mismatch')
    return folder,bundle,archive

def download(tag):
    folder=Path(tempfile.mkdtemp(prefix=tag+'-',dir=CACHE))
    try:return download_payload(tag,folder)
    except Exception:
        shutil.rmtree(folder);raise

def services(target,start):
    if start:
        if target.get('start_units',target.get('units')):target_command(target,['systemctl','start',*target.get('start_units',target.get('units',[]))])
        if target.get('containers'):command(['docker','start',*target['containers']])
    else:
        if target.get('containers'):command(['docker','stop',*target['containers']])
        if target.get('units'):target_command(target,['systemctl','stop',*target['units']])

def healthy(target,tag):
    # Health probes run in the target namespace, using only root-configured URLs.
    code='''import json,urllib.request,sys,time
for attempt in range(30):
 try:
  for url in json.loads(sys.argv[1]):
   with urllib.request.urlopen(url,timeout=5) as r:d=json.load(r)
   if url.endswith('build-info.json'):assert d.get('version')==sys.argv[2]
   if url.endswith('/api/latest'):assert isinstance(d,list) and d and time.time()-max(v['ts'] for v in d)<120
  break
 except Exception:
  if attempt==29:raise
  time.sleep(2)
'''
    if target.get('health_urls'):target_command(target,['python3','-c',code,json.dumps(target['health_urls']),tag],timeout=300)

def apply(config,folder,bundle,archive,tag):
    completed=[];stopped=[];stages=[];rollback_failed=False;updater_backup=None
    try:
        for target in config['targets']:
            source=bundle
            target_command(target,['python3','-c',"import shutil,sys; assert shutil.disk_usage(sys.argv[1]).free > 1024**3, 'At least 1 GiB free is required before updating'",target['destination']])
            if target.get('ctid'):
                stage=target_command(target,['mktemp','-d','/opt/chassisdeck/releases/update-XXXXXXXX']).strip()
                stages.append((target,stage))
                command(['pct','exec',str(target['ctid']),'--','mkdir','-p',stage])
                command(['pct','push',str(target['ctid']),str(archive),stage+'/'+archive.name],timeout=300)
                target_command(target,['tar','-xzf',stage+'/'+archive.name,'-C',stage],timeout=300)
                source=Path(stage)/('chassisdeck-'+tag)
            stopped.append(target);services(target,False)
            target_command(target,['python3',str(source/'install-release.py'),'--bundle',str(source),
                '--profile',target['profile'],'--destination',target['destination'],'--backup-root',target['backup_root']],timeout=600)
            completed.append((target,source,pin(target)['backup']))
            services(target,True);healthy(target,tag)
        # Update this trusted agent from the same release only after application checks pass.
        manifest=json.loads((bundle/'RELEASE.json').read_text())
        if 'updater' in manifest['profiles']:
            command(['python3',str(bundle/'install-release.py'),'--bundle',str(bundle),'--profile','updater','--destination','/opt/chassisdeck-updater',
                     '--backup-root','/var/lib/chassisdeck-updates/backups'],timeout=180)
            updater_backup=read(Path('/opt/chassisdeck-updater/.chassisdeck-release.json'),{})['backup']
            command(['systemctl','restart','chassisdeck-update-api.service'])
    except Exception:
        if updater_backup:
            try:
                command(['python3',str(bundle/'install-release.py'),'--restore',updater_backup,'--destination','/opt/chassisdeck-updater'])
                command(['systemctl','restart','chassisdeck-update-api.service'])
            except Exception:rollback_failed=True
        for target,source,backup in reversed(completed):
            try:
                services(target,False)
                target_command(target,['python3',str(source/'install-release.py'),'--restore',backup,'--destination',target['destination']],timeout=600)
            except Exception:rollback_failed=True
        raise RuntimeError('Update failed; manual recovery required.' if rollback_failed else 'Update failed; previous application version restored.')
    finally:
        for target,stage in stages:
            try:target_command(target,['rm','-rf','--',stage])
            except Exception:print('Staging cleanup failed; inspect release staging directory.',flush=True)
        for target in stopped:
            try:services(target,True)
            except Exception:print('Service restart failed; inspect the host journal.',flush=True)

def main():
    info=CONFIG.stat()
    if info.st_uid!=0 or info.st_mode&0o022 or CONFIG.is_symlink():raise ValueError('Worker config must be protected and root owned')
    config=json.loads(CONFIG.read_text());STATE.mkdir(exist_ok=True);CACHE.mkdir(exist_ok=True)
    with open(STATE/'worker.lock','w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        status=read(STATE/'status.json',{});settings=read(SETTINGS,{})
        enabled=settings.get('auto_enabled') is True
        requested=settings.get('check_requested',0);changed=settings.get('changed_at',0)
        if not isinstance(requested,(int,float)):requested=0
        if not isinstance(changed,(int,float)):changed=0
        current=pin(config['targets'][-1]).get('version','v0.0.0');version(current)
        status.update(current_version=current,host=config['host'],checked_at=status.get('checked_at',0))
        try:
            if time.time()-status['checked_at']>=3600 or requested>status.get('request_seen',0):
                status.update(state='checking',message='Checking stable ChassisDeck releases.');save(status)
                status.update(available_version=latest(),checked_at=time.time(),request_seen=requested)
            candidate=status.get('available_version',current)
            available=version(candidate)>version(current)
            status.update(update_available=available,state='available' if available else 'current',
                          message='A stable update is available.' if available else 'You are up to date.')
            if enabled and available:
                if status.get('failed_version')==candidate and changed<=status.get('attempted_at',0):
                    status.update(state='failed',message='Previous update failed. Review the host journal before re-enabling automatic updates.')
                else:
                    status.update(state='downloading',attempted_at=time.time(),message='Downloading and verifying the release.');save(status)
                    if shutil.disk_usage(CACHE).free<1024**3:raise ValueError('At least 1 GiB free cache space required')
                    folder,bundle,archive=download(candidate)
                    status.update(state='installing',message='Applying the verified release; the dashboard may reconnect shortly.');save(status)
                    try:apply(config,folder,bundle,archive,candidate)
                    finally:shutil.rmtree(folder)
                    status.update(state='current',message='Update installed and health checks passed.',current_version=candidate,
                                  updated_at=time.time(),update_available=False,failed_version=None)
            status['next_check']=status['checked_at']+3600
        except Exception as error:
            print(type(error).__name__+': '+str(error),flush=True)
            status.update(state='failed',message='Update check or installation failed. Inspect the host updater journal.',
                          failed_version=status.get('available_version') if enabled else status.get('failed_version'))
        save(status)

if __name__=='__main__':main()
