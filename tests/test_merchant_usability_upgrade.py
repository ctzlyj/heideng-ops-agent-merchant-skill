"""Real 0.4.0 package -> this candidate via original 0.4.0 updater, isolated/no network."""
import ast,hashlib,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from heideng_merchant.distribution import build_bundle,install_archive,validate_archive,verify_install,SKILL_NAME
from heideng_merchant.update_catalog import sign,digest
from heideng_merchant.safety import clean_environment
from scripts.publish_stable import dependency_fingerprint
from scripts.audit_release import audit
ROOT=Path(__file__).resolve().parents[1]

class UsabilityUpgradeTests(unittest.TestCase):
    def test_original_updater_installs_real_candidate_and_preserves_private_state(self):
        from heideng_merchant.update_client import configure
        old=next((ROOT/'updates/artifacts').glob('*-0.4.0-*.zip'))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'state';target=root/'skills'/SKILL_NAME
            install_archive(old,target,state,expected_sha=digest(old))
            secrets=state/'secrets';secrets.mkdir();(secrets/'fixture.dpapi').write_bytes(b'fixture-protected-bytes')
            (state/'unknown-receipt.json').write_text('{"status":"unknown","taskVersion":"0.4.0"}',encoding='utf-8')
            before={p.relative_to(state).as_posix():p.read_bytes() for p in (secrets/'fixture.dpapi',state/'unknown-receipt.json')}
            candidate=build_bundle(ROOT,root/'candidate.zip','0.4.1');manifest,files=validate_archive(candidate)
            old_manifest,old_files=validate_archive(old)
            self.assertEqual(dependency_fingerprint(files),dependency_fingerprint(old_files))
            self.assertEqual(audit(candidate)['releaseAudit'],'passed')
            self.assertIn('scripts/runtime_preflight.py',files);self.assertIn('heideng_merchant/merchant_key_store.py',files)
            def prompts(raw):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(raw.decode('utf-8')).body if isinstance(n,ast.FunctionDef) and n.name in ('_shared_image_rules','image_prompt')}
            self.assertEqual(prompts(files['mature/materials/scripts/jd_material_agent.py']),prompts(old_files['mature/materials/scripts/jd_material_agent.py']))
            def prompt_source(raw):
                text=raw.decode('utf-8');return {n.name:ast.get_source_segment(text,n) for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name in ('_shared_image_rules','image_prompt')}
            self.assertEqual(prompt_source(files['mature/materials/scripts/jd_material_agent.py']),prompt_source(old_files['mature/materials/scripts/jd_material_agent.py']))
            key=Ed25519PrivateKey.generate();public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
            trust={'schemaVersion':1,'repository':'ctzlyj/heideng-ops-agent-merchant-skill','ref':'refs/heads/codex/merchant-foundation','keys':{'fixture':public}}
            configure(state,target,trust,host='workbuddy')
            release={'id':'fixture-0.4.1','version':'0.4.1','status':'stable','gitBlob':'fixture','sha256':digest(candidate),'sizeBytes':candidate.stat().st_size,'dependencyFingerprint':dependency_fingerprint(files),'components':{n.split('/')[1]:json.loads(v)['upstreamCommit'] for n,v in files.items() if n.startswith('mature/') and n.endswith('/provenance.json')},'compatibility':{'pythonMinimum':'3.11','hosts':['workbuddy']}}
            envelope=sign({'schemaVersion':1,'repository':trust['repository'],'sequence':2,'issuedAt':time.time(),'expiresAt':time.time()+3600,'releases':[release]},key,'fixture')
            (root/'catalog.json').write_text(json.dumps(envelope),encoding='utf-8')
            code="""import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from heideng_merchant import update_client as u
class Source:
 def read_index(self):return json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
 def read_blob(self,oid):return Path(sys.argv[4]).read_bytes()
print(json.dumps(u.apply(Path(sys.argv[2]),source=Source())))
"""
            result=subprocess.run([sys.executable,'-I','-B','-c',code,str(target),str(state),str(root/'catalog.json'),str(candidate)],env=clean_environment(root/'process-home'),capture_output=True,text=True,encoding='utf-8',timeout=60)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['status'],'installed')
            self.assertEqual(verify_install(target)['version'],'0.4.1')
            for name,raw in before.items():self.assertEqual((state/name).read_bytes(),raw)

    def test_image_key_entry_fails_before_dialog_when_no_frozen_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'state'
            env=clean_environment(root/'home');env['HEIDENG_MERCHANT_PYTHON312']=sys.executable
            command=[sys.executable,'-I','-B',str(ROOT/'scripts/with_image_key.py'),'--state',str(state),'run','materials','--','auto-maintain','--profile','fixture','--expected-shop-name','fixture','--output-dir',str(root/'work'),'--confirm','AUTO_MAINTAIN']
            result=subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8',timeout=20)
            self.assertEqual(result.returncode,2,result.stderr);data=json.loads(result.stdout.strip().splitlines()[-1])
            self.assertFalse(data['businessExecuted']);self.assertIn('preflight',data['error'])
            self.assertFalse((state/'secrets').exists())

if __name__=='__main__':unittest.main()
