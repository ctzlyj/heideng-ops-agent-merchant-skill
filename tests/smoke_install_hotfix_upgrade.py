"""Upgrade exact source snapshots in a synthetic home; no CLI download or OAuth."""
import argparse,json,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.distribution import verify_install,version_key
from heideng_merchant.safety import clean_environment,file_sha

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--old-source',required=True);parser.add_argument('--candidate-source',required=True);args=parser.parse_args()
 old=Path(args.old_source).resolve();candidate=Path(args.candidate_source).resolve()
 new_version=(candidate/'VERSION').read_text(encoding='utf-8-sig').strip();assert version_key(new_version)>version_key('0.1.1')
 with tempfile.TemporaryDirectory(prefix='merchant-upgrade-smoke-') as d:
  home=Path(d).resolve();env=clean_environment(home);env['PYTHONUTF8']='1'
  def execute(source):
   process=subprocess.run([sys.executable,'-I',str(source/'install.py'),'--home',str(home),'--host','joycode','--offline'],env=env,cwd=home,capture_output=True)
   if process.returncode:raise AssertionError('synthetic upgrade rejected: '+str(process.returncode))
   return json.loads(process.stdout)
  first=execute(old);assert first['version']=='0.1.1' and first['status']=='installed'
  target=home/'.joycode/skills/heideng-ops-agent-merchant'
  old_receipt=file_sha(target/'.merchant-install.json')
  sentinel=home/'synthetic-state.txt';sentinel.write_text('preserved',encoding='utf-8')
  second=execute(candidate);assert second['version']==new_version and second['status']=='installed'
  assert verify_install(target)['valid'] and (target/'VERSION').read_text().strip()==new_version
  assert file_sha(target/'.merchant-install.json')!=old_receipt and sentinel.read_text()=='preserved'
  third=execute(candidate);assert third['status']=='unchanged' and third['version']==new_version
  runtime=subprocess.run([sys.executable,'-I',str(target/'scripts/merchant.py'),'--home',str(home),'onboarding'],env=env,cwd=home,capture_output=True)
  assert runtime.returncode==0 and json.loads(runtime.stdout)['version']==new_version
 print(json.dumps({'status':'passed','oldVersion':'0.1.1','candidateVersion':new_version,'directUpgrade':True,'rollbackInvoked':False,'integrityVerified':True,'idempotent':True,'installedRuntimeVersion':new_version,'syntheticStatePreserved':True,'realMerchantHome':'not-accessed','cliDownload':'not-run','realCredentials':'none'}))
if __name__=='__main__':main()
