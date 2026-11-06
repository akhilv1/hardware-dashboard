import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('release_install',Path(__file__).with_name('install-release.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ReleaseTests(unittest.TestCase):
    def fixture(self,root):
        bundle=root/'bundle';(bundle/'payload').mkdir(parents=True)
        (bundle/'payload/new.txt').write_text('new')
        manifest=dict(repository='example/app',version='v0.1.0',commit='a'*40,
            files={'new.txt':hashlib.sha256(b'new').hexdigest()},
            profiles={'linux':{'index.html':'new.txt','assets/new.txt':'new.txt'}})
        (bundle/'RELEASE.json').write_text(json.dumps(manifest))
        dest=root/'live';dest.mkdir();(dest/'index.html').write_text('old')
        (dest/'telemetry').mkdir();(dest/'telemetry/data').write_text('keep')
        return bundle,dest,root/'backups'
    def test_install_and_restore_preserve_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle,dest,backups=self.fixture(Path(tmp))
            backup=module.install(bundle,dest,'linux',backups)
            self.assertEqual((dest/'index.html').read_text(),'new')
            self.assertEqual((dest/'telemetry/data').read_text(),'keep')
            module.restore(backup,dest)
            self.assertEqual((dest/'index.html').read_text(),'old')
            self.assertFalse((dest/'assets/new.txt').exists())
            self.assertFalse((dest/'.chassisdeck-release.json').exists())
    def test_corruption_refused_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle,dest,backups=self.fixture(Path(tmp));(bundle/'payload/new.txt').write_text('corrupt')
            with self.assertRaises(ValueError):module.install(bundle,dest,'linux',backups)
            self.assertEqual((dest/'index.html').read_text(),'old');self.assertFalse(backups.exists())
    def test_symlink_escape_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle,dest,backups=self.fixture(Path(tmp));outside=Path(tmp)/'outside';outside.mkdir();(dest/'assets').symlink_to(outside)
            with self.assertRaises(ValueError):module.install(bundle,dest,'linux',backups)
            self.assertEqual((dest/'index.html').read_text(),'old');self.assertEqual(list(outside.iterdir()),[])
    def test_local_modifications_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle,dest,backups=self.fixture(Path(tmp));module.install(bundle,dest,'linux',backups)
            (dest/'index.html').write_text('local work')
            with self.assertRaises(ValueError):module.install(bundle,dest,'linux',backups)
            self.assertEqual((dest/'index.html').read_text(),'local work')
    def test_partial_write_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle,dest,backups=self.fixture(Path(tmp))
            real=module.atomic_copy
            calls=0
            def fail_second(source,target):
                nonlocal calls
                calls+=1
                if calls==2:raise OSError('synthetic write failure')
                real(source,target)
            with patch.object(module,'atomic_copy',side_effect=fail_second):
                with self.assertRaises(OSError):module.install(bundle,dest,'linux',backups)
            self.assertEqual((dest/'index.html').read_text(),'old')
            self.assertFalse((dest/'.chassisdeck-release.json').exists())
    def test_updater_profile_installs_through_release_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle,dest,backups=self.fixture(Path(tmp))
            manifest=json.loads((bundle/'RELEASE.json').read_text())
            manifest['profiles']['updater']={'update_worker.py':'new.txt'}
            (bundle/'RELEASE.json').write_text(json.dumps(manifest))
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('install-release.py')),
                '--bundle',str(bundle),'--profile','updater','--destination',str(dest),
                '--backup-root',str(backups)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((dest/'update_worker.py').read_text(),'new')
            self.assertEqual(json.loads((dest/'.chassisdeck-release.json').read_text())['profile'],'updater')
            self.assertEqual((dest/'telemetry/data').read_text(),'keep')
    def test_traversal_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for path in ('../escape','/absolute'):
                with self.assertRaises(ValueError):module.safe_path(Path(tmp),path)

if __name__=='__main__':unittest.main()
