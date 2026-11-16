"""Concrete review regressions: original upgrade guard and installed boundaries."""
import io, json, subprocess, sys, tarfile, tempfile, unittest
from pathlib import Path
from heideng_merchant.distribution import build_bundle,install_archive
from heideng_merchant.safety import SafetyError,file_sha
from heideng_merchant.mature_runtime import child_environment
ROOT=Path(__file__).resolve().parents[1]
BASELINE='10132cf831d26a4e2984540665f418951acfbb52'

class ReviewRegressions(unittest.TestCase):
    def test_original_guard_sees_orphan_video_evidence_outside_old_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);source=base/'old-source';source.mkdir()
            try:raw=subprocess.check_output(['git','-C',str(ROOT),'archive',BASELINE],stderr=subprocess.DEVNULL)
            except (OSError,subprocess.CalledProcessError):self.skipTest('genuine baseline Git object unavailable')
            with tarfile.open(fileobj=io.BytesIO(raw)) as archive:archive.extractall(source,filter='data')
            bundle=build_bundle(source,base/'old.zip','0.1.5')
            target=base/'skills'/'heideng-ops-agent-merchant';state=base/'state'
            install_archive(bundle,target,state,expected_sha=file_sha(bundle))
            original=(target/'.merchant-install.json').read_bytes()
            orphan=state/'video-session-attempts'/('a'*24+'.json');orphan.parent.mkdir();orphan.write_text('{}')
            probe="import sys;sys.path.insert(0,sys.argv[1]);from heideng_merchant.update_gate import busy;print(busy(sys.argv[2]))"
            observed=subprocess.check_output([sys.executable,'-I','-c',probe,str(target),str(state)],text=True).strip()
            self.assertEqual(observed,'True','genuine old guard must reject this orphan')
            from heideng_merchant.installation_guard import check_legacy_update
            with self.assertRaisesRegex(SafetyError,'active-task-update-deferred'):
                check_legacy_update(target,state,'0.1.5')
            self.assertEqual((target/'.merchant-install.json').read_bytes(),original)
            self.assertTrue(orphan.exists())

    def test_signed_url_result_is_downloadable_from_actual_installed_core(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);bundle=build_bundle(ROOT,base/'new.zip',(ROOT/'VERSION').read_text().strip())
            target=base/'skills'/'heideng-ops-agent-merchant'
            install_archive(bundle,target,base/'state',expected_sha=file_sha(bundle))
            # Synthetic transport; original URL-result path and relative imports are real.
            code=r"""import sys,io,json;from pathlib import Path
sys.path.insert(0,sys.argv[1]);from heideng_merchant import lts4ai_client as c
calls=[]
class Response(io.BytesIO):
 def __init__(self,data,mime):super().__init__(data);self.headers={'Content-Type':mime}
class Opener:
 def open(self,request,timeout=None):
  calls.append(request.get_method())
  if request.get_method()=='POST':return Response(json.dumps({'data':[{'url':'https://results.example.invalid/a.png?signature=fixture'}]}).encode(),'application/json')
  return Response(b'\x89PNG\r\n\x1a\n' + b'synthetic-result','image/png')
c.urllib.request.build_opener=lambda *args:Opener()
client=c.SfImage2Client('synthetic-merchant-marker',retries=0)
result=client.generate('synthetic product','1024x1024',Path(sys.argv[2]))
print(json.dumps({'calls':calls,'bytes':result.path.read_bytes().hex()}))
"""
            child=subprocess.run([sys.executable,'-I','-c',code,str(target),str(base/'output')],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(child.returncode,0,child.stderr[-1500:])
            data=json.loads(child.stdout)
            self.assertEqual(data['calls'],['POST','GET'])
            self.assertTrue(data['bytes'].startswith('89504e470d0a1a0a'))
            self.assertFalse((target/'heideng_merchant/providers.py').exists())

    def test_parent_browser_prefix_reaches_mature_adapter_without_path_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d);fake=state/'synthetic_webcli.py'
            fake.write_text('import sys,json;print(json.dumps({"argv":sys.argv[1:],"input":sys.stdin.read()}))')
            env=child_environment(state,{'PATH':'','HEIDENG_MERCHANT_WEBCLI_COMMAND':json.dumps([sys.executable,'-I',str(fake)])})
            code="import sys,json;sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8');sys.path.insert(0,sys.argv[1]);import browser_runtime as b;print(b.WebCliRunner().run(['browser','snapshot'],input_text='synthetic input'))"
            child=subprocess.run([sys.executable,'-I','-c',code,str(ROOT/'mature/comparison/scripts')],env=env,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(child.returncode,0,child.stderr[-1500:])
            self.assertEqual(json.loads(child.stdout),{'argv':['browser','snapshot'],'input':'synthetic input'})

if __name__=='__main__':unittest.main()
