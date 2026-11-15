"""New HOME/native import API; actual UI methods with synthetic browser/backend only."""
import sys,json,tempfile,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import clean_environment,file_sha,atomic_json
CHILD=r'''import sys,socket,json
from pathlib import Path
installed,source,home=map(Path,sys.argv[1:4]);sys.path[:0]=[str(installed),str(source)]
from heideng_merchant import short_title_imports,short_title_import_state,short_title_import_browser,short_title_import_contract,short_title_import_gate,state,distribution,cli
from tests import test_short_title_imports as fixtures
from unittest.mock import patch
mods=(short_title_imports,short_title_import_state,short_title_import_browser,short_title_import_contract,short_title_import_gate,state,cli)
assert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in mods)
socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('synthetic-only'))
socket.create_connection=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('synthetic-only'))
root=home/'.heideng-merchant';c,s,p,src,m,r=fixtures.ShortTitleImportsTests().make(root);assert not distribution.busy(root)
with patch('heideng_merchant.cli.OfficialClient',return_value=c),patch('heideng_merchant.cli.ShortTitleImports',return_value=m):
 command=lambda name,*args:cli.run(cli.parser().parse_args(['--home',str(home),name,*map(str,args)]))
 assert command('short-title-import-plan','--plan-id',p['planId'],'--source-id',src['sourceId'])['importId']==r['importId']
 a=command('short-title-import-approve','--import-id',r['importId'],'--fingerprint',r['fingerprint'],'--confirm');assert a['approvalCurrentlyValid'] and a['CLIWorkerIntegrated'] and not a['imported']
f,b=fixtures.ShortTitleImportsTests().browser(root,m,r);f.driver.context.page.fault='create-timeout'
try:
 out=m.execute(r['importId'],b);assert out['status']=='unknown' and not out['imported'];assert f.driver.context.page.uploads==1 and f.driver.context.page.creates==1
 assert m.execute(r['importId'],b)['status']=='unknown' and f.driver.context.page.creates==1
 out=m.recover(r['importId'],b);assert out['submittedBatchCount']==1 and not out['imported'] and not out['actualTitlesVerified'];assert f.driver.context.page.uploads==1 and f.driver.context.page.creates==1
finally:b.close()
assert distribution.busy(root);assert not c.posts
raw=''.join(x.read_text() for x in root.rglob('*.json'));assert 'synthetic-only-private' not in raw and '?token=' not in raw
print(json.dumps({'status':'passed','installedModulePaths':True,'nativeFileUploadCalls':1,'nativeCreateCalls':1,'lostCreateAckReadOnlyRecovered':True,'noReplay':True,'unknownAndSubmittedBlockUpdates':True,'actualBrowserLaunched':False,'realMerchantCalls':0,'paidModels':0,'imported':False,'CLIWorkerIntegrated':True,'NativeWorkerExercised':False}))
'''
def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';sha=file_sha(archive);base=ROOT/'.agent-work/short-title-import-audit';base.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='ht-import-') as d:
  home=Path(d);env=clean_environment(home);child=home/'installed.py';child.write_text(CHILD,encoding='utf-8')
  for stage,args in [('install',[sys.executable,'-I','-X','utf8','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha]),('chain',[sys.executable,'-I','-X','utf8','-B',child,home/'.codex/skills/heideng-ops-agent-merchant',ROOT,home])]:
   r=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,timeout=300);(base/(stage+'.log')).write_bytes(r.stdout+r.stderr);assert r.returncode==0,'installed native import smoke failed: '+stage
   if stage=='chain':result=json.loads(r.stdout)
 assert file_sha(archive)==sha;record={'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'businessAndBrowser':'synthetic','automaticMerchantCLIImportComplete':False,'result':result,'goalComplete':False};atomic_json(base/'installed-short-title-import-smoke.json',record);print(json.dumps(record))
if __name__=='__main__':main()
