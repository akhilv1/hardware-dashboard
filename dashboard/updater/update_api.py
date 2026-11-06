"""Unprivileged, authenticated settings API over a dedicated Unix socket."""
from http.server import BaseHTTPRequestHandler
from http.cookies import SimpleCookie
import hashlib
import json
import os
from pathlib import Path
import secrets
import socketserver
import tempfile
import threading
import time

CONFIG = Path('/etc/chassisdeck-updater/api.json')
STATE = Path('/var/lib/chassisdeck-update-api')
STATUS = Path('/var/lib/chassisdeck-updates/status.json')
COOKIE = 'chassisdeck_updates'
COOKIE_PATH = '/hardware/api/updates'
SESSIONS = {}
ATTEMPTS = []
GUARD = threading.Lock()

def read_json(path, default):
    try:
        if path.is_symlink() or path.stat().st_size > 65536: return default
        return json.loads(path.read_text())
    except (OSError, ValueError): return default

def settings():
    value = read_json(STATE/'settings.json', {})
    if not isinstance(value,dict): value={}
    for key in ('changed_at','check_requested'):
        if type(value.get(key)) not in (int,float): value[key]=0
    return {'auto_enabled':value.get('auto_enabled') is True,
            'changed_at':value.get('changed_at',0), 'check_requested':value.get('check_requested',0)}

def save(value):
    fd, name = tempfile.mkstemp(prefix='.settings-',dir=STATE)
    try:
        with os.fdopen(fd,'w') as out:
            json.dump(value,out);out.flush();os.fsync(out.fileno())
        os.chmod(name,0o644);os.replace(name,STATE/'settings.json')
    finally:
        if os.path.exists(name):os.unlink(name)

def valid_token(token, config):
    return isinstance(token,str) and len(token)<=256 and secrets.compare_digest(
        hashlib.sha256(token.encode()).hexdigest(),config['token_sha256'])

class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads=True
    request_queue_size=8
    def __init__(self,*args,**kwargs):
        self.slots=threading.BoundedSemaphore(8);super().__init__(*args,**kwargs)
    def get_request(self):
        request,address=super().get_request();request.settimeout(5);return request,address
    def process_request(self,request,address):
        if not self.slots.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()

class Handler(BaseHTTPRequestHandler):
    server_version='ChassisDeckUpdates'
    def reply(self,code,data,cookie=None):
        body=json.dumps(data,allow_nan=False).encode()
        self.send_response(code);self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(body)))
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(body)
    def session(self):
        try:
            cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
            value=cookies[COOKIE].value
        except (KeyError,ValueError):return False
        with GUARD:
            now=time.time()
            for key in list(SESSIONS):
                if SESSIONS[key]<now:del SESSIONS[key]
            return SESSIONS.get(hashlib.sha256(value.encode()).hexdigest(),0)>now
    def cookie(self,value,max_age):
        secure='; Secure' if self.headers.get('Origin','').startswith('https://') else ''
        return f'{COOKIE}={value}; Path={COOKIE_PATH}; Max-Age={max_age}; HttpOnly; SameSite=Strict{secure}'
    def do_GET(self):
        if self.path!='/api/updates':self.reply(404,{'error':'Not found'});return
        status=read_json(STATUS,{'state':'waiting','message':'Waiting for the first release check.'})
        self.reply(200,{'settings':settings(),'status':status,'authenticated':self.session(),
                       'channel':'Stable releases','repository':'akhilv1/hardware-dashboard'})
    def do_POST(self):
        config=read_json(CONFIG,{})
        if (self.headers.get('Origin') not in config.get('origins',[]) or
            self.headers.get('X-ChassisDeck-Update')!='1'):
            self.reply(403,{'error':'Same-origin update requests required'});return
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':
            self.reply(415,{'error':'JSON required'});return
        lengths=self.headers.get_all('Content-Length',[])
        if len(lengths)!=1 or self.headers.get('Transfer-Encoding') or len(str(self.headers))>8192:
            self.reply(400,{'error':'Invalid request'});return
        try:
            length=int(lengths[0])
            if not 0<length<=2048:raise ValueError()
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):raise ValueError()
        except (ValueError,TimeoutError):self.reply(400,{'error':'Invalid request'});return
        if self.path=='/api/updates/login':
            with GUARD:
                now=time.time();ATTEMPTS[:]=[t for t in ATTEMPTS if now-t<60]
                limited=len(ATTEMPTS)>=5
                if not limited:ATTEMPTS.append(now)
            if limited:self.reply(429,{'error':'Too many attempts. Try again in one minute.'});return
            if set(data)!={'token'} or not config.get('token_sha256') or not valid_token(data['token'],config):
                self.reply(401,{'error':'Invalid admin key'});return
            token=secrets.token_urlsafe(32)
            with GUARD:
                if len(SESSIONS)>=32:SESSIONS.pop(next(iter(SESSIONS)))
                SESSIONS[hashlib.sha256(token.encode()).hexdigest()]=time.time()+3600
            self.reply(200,{'authenticated':True},self.cookie(token,3600));return
        if not self.session():self.reply(401,{'error':'Unlock update settings first'});return
        if self.path=='/api/updates/logout':
            cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
            with GUARD:SESSIONS.pop(hashlib.sha256(cookies[COOKIE].value.encode()).hexdigest(),None)
            self.reply(200,{'authenticated':False},self.cookie('',0));return
        with GUARD:
            value=settings()
            if self.path=='/api/updates/settings':
                if set(data)!={'auto_enabled'} or type(data['auto_enabled']) is not bool:
                    self.reply(400,{'error':'Only the auto-update boolean can be changed'});return
                value['auto_enabled']=data['auto_enabled'];value['changed_at']=time.time()
            elif self.path=='/api/updates/check':
                if data or time.time()-value['check_requested']<60:
                    self.reply(429,{'error':'Please wait one minute between checks'});return
                value['check_requested']=time.time()
            else:self.reply(404,{'error':'Not found'});return
            save(value)
        self.reply(200,{'settings':value,'message':'Saved. The host updater will pick this up within one minute.'})
    def log_message(self,*args):pass

if __name__=='__main__':
    socket=STATE/'run/control.sock';socket.parent.mkdir(parents=True,exist_ok=True)
    if socket.exists():socket.unlink()
    with Server(str(socket),Handler) as server:
        os.chmod(socket,0o666)
        server.serve_forever()
