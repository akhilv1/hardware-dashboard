import hashlib
import http.client
import io
import json
from pathlib import Path
import socket
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
import update_api as api
import update_worker as worker

class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.connect(self.host)

class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.patches=[patch.object(api,'STATE',root),patch.object(api,'CONFIG',root/'api.json'),patch.object(api,'STATUS',root/'status.json')]
        for p in self.patches:p.start()
        api.CONFIG.write_text(json.dumps({'origins':['https://deck.test'],'token_sha256':hashlib.sha256(b'test-only-key').hexdigest()}))
        api.SESSIONS.clear();api.ATTEMPTS.clear()
        self.server=api.Server(str(root/'control.sock'),api.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.cookie=''
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        for p in self.patches:p.stop()
        self.tmp.cleanup()
    def request(self,path='',data=None,origin='https://deck.test'):
        c=UnixHTTP(self.server.server_address,timeout=3)
        headers={'Origin':origin,'X-ChassisDeck-Update':'1','Content-Type':'application/json','Cookie':self.cookie}
        c.request('GET' if data is None else 'POST','/api/updates'+path,None if data is None else json.dumps(data),headers)
        r=c.getresponse();body=json.loads(r.read());cookie=r.getheader('Set-Cookie');status=r.status;c.close()
        if cookie:self.cookie=cookie.split(';')[0]
        return status,body,cookie
    def login(self):
        code,_,cookie=self.request('/login',{'token':'test-only-key'})
        self.assertEqual(code,200);self.assertIn('HttpOnly',cookie);self.assertIn('Secure',cookie);self.assertIn('SameSite=Strict',cookie)
    def test_default_off_and_no_credentials_in_status(self):
        code,data,_=self.request();self.assertEqual(code,200)
        self.assertFalse(data['settings']['auto_enabled']);self.assertNotIn('token',json.dumps(data))
    def test_mutations_require_auth_and_exact_origin(self):
        self.assertEqual(self.request('/settings',{'auto_enabled':True})[0],401)
        self.login()
        self.assertEqual(self.request('/settings',{'auto_enabled':True},'https://evil.test')[0],403)
        self.assertEqual(self.request('/settings',{'auto_enabled':True},'null')[0],403)
        self.assertFalse(api.settings()['auto_enabled'])
    def test_toggle_persists_and_logout_revokes(self):
        self.login();self.assertEqual(self.request('/settings',{'auto_enabled':True})[0],200)
        self.assertTrue(api.settings()['auto_enabled'])
        self.assertEqual(self.request('/settings',{'auto_enabled':False})[0],200)
        self.assertFalse(api.settings()['auto_enabled'])
        self.request('/logout',{});self.assertEqual(self.request('/settings',{'auto_enabled':True})[0],401)
    def test_no_commands_urls_or_coerced_booleans(self):
        self.login()
        for data in ({'auto_enabled':'true'},{'auto_enabled':1},{'auto_enabled':True,'url':'https://evil.test'},{'command':'id'}):
            self.assertEqual(self.request('/settings',data)[0],400)
    def test_checks_are_rate_limited(self):
        self.login();self.assertEqual(self.request('/check',{})[0],200)
        self.assertEqual(self.request('/check',{})[0],429)
    def test_login_rate_limit(self):
        for _ in range(5):self.assertEqual(self.request('/login',{'token':'wrong'})[0],401)
        self.assertEqual(self.request('/login',{'token':'test-only-key'})[0],429)

class WorkerTests(unittest.TestCase):
    def test_stable_versions_only(self):
        self.assertGreater(worker.version('v0.10.0'),worker.version('v0.9.0'))
        for value in ('latest','v1.0.0-rc1','../v1.0.0','v1.2.3/x'):
            with self.assertRaises(ValueError):worker.version(value)
    def test_archive_rejects_traversal_and_links(self):
        for name,kind in (('chassisdeck-v1.0.0/../../evil',tarfile.REGTYPE),('chassisdeck-v1.0.0/link',tarfile.SYMTYPE)):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);archive=root/'bad.tgz'
                with tarfile.open(archive,'w:gz') as out:
                    item=tarfile.TarInfo(name);item.type=kind;item.linkname='/etc/passwd';out.addfile(item)
                with self.assertRaises(ValueError):worker.unpack(archive,root/'out','v1.0.0')
    def test_redirect_rejects_other_origins_before_following(self):
        with self.assertRaises(ValueError):worker.ReleaseRedirect().redirect_request(None,None,302,'',{},'http://169.254.169.254/')
    def test_missing_or_external_release_assets_rejected(self):
        with patch.object(worker,'fetch',return_value=json.dumps({'tag_name':'v1.0.0','assets':[]}).encode()):
            with self.assertRaises(ValueError):worker.latest()
    def test_corrupt_download_never_reaches_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fetch(url,limit,destination=None):
                if destination:Path(destination).write_bytes(b'corrupt');return b''
                return (('0'*64)+'  chassisdeck-v1.0.0.tar.gz\n').encode()
            with patch.object(worker,'fetch',side_effect=fetch),patch.object(worker,'unpack') as extract:
                with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                    worker.download_payload('v1.0.0',Path(tmp))
                extract.assert_not_called()
    def test_disabled_setting_never_downloads_or_installs(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'worker.json';settings=root/'settings.json'
            config.write_text(json.dumps({'host':'test','targets':[{'destination':str(root)}]}))
            settings.write_text('{"auto_enabled":false}')
            (root/'.chassisdeck-release.json').write_text('{"version":"v1.0.0"}')
            (root/'status.json').write_text(json.dumps({'checked_at':time.time(),'available_version':'v2.0.0'}))
            class ProtectedConfig:
                def stat(self):return type('Stat',(),{'st_uid':0,'st_mode':0o600})()
                def is_symlink(self):return False
                def read_text(self):return config.read_text()
            with patch.object(worker,'CONFIG',ProtectedConfig()),patch.object(worker,'STATE',root),patch.object(worker,'CACHE',root/'cache'),patch.object(worker,'SETTINGS',settings),patch.object(worker,'download') as download,patch.object(worker,'apply') as apply:
                worker.main();download.assert_not_called();apply.assert_not_called()
                self.assertTrue(json.loads((root/'status.json').read_text())['update_available'])
    def test_health_failure_rolls_back_and_restarts(self):
        target={'destination':'/opt/deck','profile':'linux','backup_root':'/backups'}
        with patch.object(worker,'target_command') as cmd,patch.object(worker,'services') as services,patch.object(worker,'pin',return_value={'backup':'/backups/release'}),patch.object(worker,'healthy',side_effect=RuntimeError('bad')):
            with self.assertRaisesRegex(RuntimeError,'previous application version restored'):
                worker.apply({'targets':[target]},Path('/stage'),Path('/stage/bundle'),Path('/stage/release.tgz'),'v1.0.0')
            self.assertTrue(any('--restore' in args[0][1] for args in cmd.call_args_list))
            self.assertEqual(services.call_args.args,(target,True))

if __name__=='__main__':unittest.main()
