"""Fresh install; task-owned browser/source adapter using synthetic pages only."""
import json,sys,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import file_sha,clean_environment,atomic_json
CHILD=r'''import sys,socket,json
from pathlib import Path
installed,source,home=map(Path,sys.argv[1:4]);sys.path[:0]=[str(installed),str(source)]
from heideng_merchant import short_title_browser,short_title_browser_contract,short_titles,short_title_browser_gate,distribution
from heideng_merchant.safety import SafetyError
from tests.test_short_title_browser import ShortTitleBrowserTests
assert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in (short_title_browser,short_title_browser_contract,short_titles,short_title_browser_gate,distribution))
socket.socket.connect=lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('synthetic-only'))
socket.create_connection=lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('synthetic-only'))
state=home/'.heideng-merchant';state.mkdir(exist_ok=True);c,s,p,f,b=ShortTitleBrowserTests().make(state);b.open()
try:
 assert distribution.busy(state);r=b.capture();assert distribution.busy(state);assert r['status']=='source-captured' and r['browserIdentityVerified'] and r['templateOriginCaptured'] and not r['taskListComplete'] and not r['writeExecutionAvailable'] and not r['imported'] and not r['approvalReady'];assert r['observedInstanceIds']==['123456'] and r['observedTaskRowCount']==2
 assert not c.posts and len(f.driver.launches)==1 and Path(f.driver.launches[0][0]).is_relative_to(state);assert 'JD_LLM_API_KEY' not in f.driver.launches[0][1]['env']
 try:b.capture()
 except SafetyError:pass
 else:raise AssertionError('duplicate source capture accepted')
finally:b.close()
assert f.driver.context.closed and f.driver.stopped;assert not distribution.busy(state);assert short_title_browser.read_source(state,c,r['sourceId'])['historicalCapture'];raw='\n'.join(x.read_text() for x in state.rglob('*.json'));assert 'synthetic-only-private' not in raw and '?token=' not in raw
print(json.dumps({'status':'passed','installedModulePaths':True,'taskOwnedProfile':True,'activeAndClosedUpdateGate':True,'sameObjectIdentity':True,'observedTaskRows':2,'instanceIds':['123456'],'templateOriginCaptured':'synthetic browser event','taskListComplete':False,'actualBrowserLaunched':False,'realMerchantCalls':0,'paidModels':0,'imported':False,'approvalReady':False}))
'''
def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';sha=file_sha(archive);base=ROOT/'.agent-work/short-title-browser-source-audit';base.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='ht-browser-') as d:
  home=Path(d);env=clean_environment(home);child=home/'installed.py';child.write_text(CHILD,encoding='utf-8')
  for stage,args in [('install',[sys.executable,'-I','-X','utf8','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha]),('chain',[sys.executable,'-I','-X','utf8','-B',child,home/'.codex/skills/heideng-ops-agent-merchant',ROOT,home])]:
   r=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,timeout=180);(base/(stage+'.log')).write_bytes(r.stdout+r.stderr);assert r.returncode==0,'installed browser-source smoke failed: '+stage
   if stage=='chain':result=json.loads(r.stdout)
 assert file_sha(archive)==sha;record={'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'sourceAndMerchantCalls':'synthetic','actualBrowserLaunched':False,'writeExecutionAvailable':False,'result':result,'goalComplete':False};atomic_json(base/'installed-short-title-browser-source-smoke.json',record);print(json.dumps(record))
if __name__=='__main__':main()
