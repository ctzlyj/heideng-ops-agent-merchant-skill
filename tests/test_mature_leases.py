"""Program-version lease: parallel mature tasks permitted, update remains exclusive."""
import subprocess, sys, tempfile, time, unittest
from pathlib import Path
from heideng_merchant.state import FileLock
from heideng_merchant.safety import SafetyError
ROOT=Path(__file__).resolve().parents[1]

class MatureLeaseTests(unittest.TestCase):
    def test_two_real_readers_coexist_and_block_directory_switch(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);lock=base/'install.lock';ready=base/'ready';release=base/'release'
            code="""import sys,time;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from heideng_merchant.state import FileLock;lock,ready,release=map(Path,sys.argv[2:]);
with FileLock(lock,shared=True):
 ready.write_text('ready');
 while not release.exists():time.sleep(.03)"""
            with FileLock(lock,shared=True):
                child=subprocess.Popen([sys.executable,'-I','-c',code,str(ROOT),str(lock),str(ready),str(release)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                try:
                    deadline=time.monotonic()+8
                    while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.03)
                    self.assertTrue(ready.exists(), 'second mature task blocked by first task')
                    with self.assertRaisesRegex(SafetyError,'resource-busy'):
                        with FileLock(lock,timeout=.1):pass
                finally:
                    release.write_text('release')
                    out,error=child.communicate(timeout=10)
                    self.assertEqual(child.returncode,0,error.decode('utf-8','replace'))
            with FileLock(lock,timeout=.1):pass

    def test_detached_source_launcher_keeps_read_lease_after_dispatcher_returns(self):
        import json,os,shutil
        from heideng_merchant.mature_runtime import child_environment
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);package=base/'package';state=base/'state';package.mkdir();state.mkdir()
            for n in json.loads((ROOT/'package-files.json').read_text(encoding='utf-8'))['files']:
                source=ROOT/n;target=package/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            entry=package/'mature/listing/scripts/fixture.py';entry.parent.mkdir(parents=True)
            entry.write_text("import os,time;from pathlib import Path;s=Path(os.environ['HEIDENG_MERCHANT_HOME']);(s/'ready').write_text('ready');\nwhile not (s/'release').exists():time.sleep(.03)\n")
            env=child_environment(state);env['HEIDENG_MERCHANT_PACKAGE']=str(package)
            child=subprocess.Popen([sys.executable,'-I','-B',str(package/'scripts/mature_entry.py'),str(entry)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+8
                while not (state/'ready').exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.03)
                self.assertTrue((state/'ready').exists())
                with self.assertRaisesRegex(SafetyError,'resource-busy'):
                    with FileLock(state/'install.lock',timeout=.1):pass
            finally:
                (state/'release').write_text('release');out,error=child.communicate(timeout=10)
                self.assertEqual(child.returncode,0,error.decode('utf-8','replace'))
            with FileLock(state/'install.lock',timeout=.1):pass

if __name__=='__main__':unittest.main()
