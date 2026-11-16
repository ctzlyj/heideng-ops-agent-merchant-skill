"""Thin browser transport must preserve original collector's page contract and tab ownership."""
import json,os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SCRIPTS=ROOT/'mature/collection/scripts'
class CollectionTransportTests(unittest.TestCase):
 def test_packaged_transport_exists_without_company_preload(self):
  text=(SCRIPTS/'owned_cdp_transport.mjs').read_text(encoding='utf-8')
  self.assertNotIn('o2',text.lower());self.assertNotIn('preload',text.lower())
 def test_original_mature_request_limit_is_not_reduced_to_new_twenty_gate(self):
  code="const {pathToFileURL}=require('node:url');(async()=>{const p=await import(pathToFileURL(process.argv[1]));const options=p.parseOptions(['--root','fixture','--max-requests','45']);if(options.maxRequests!==45)throw Error('lost original limit');})().catch(e=>{console.error(e.message);process.exit(1)});"
  env=dict(os.environ);env.pop('HEIDENG_COLLECTION_MAX_REQUEST_LIMIT',None)
  result=subprocess.run(['node','-e',code,str(SCRIPTS/'collection_policy.mjs')],env=env,capture_output=True,text=True,encoding='utf-8',timeout=20)
  self.assertEqual(result.returncode,0,result.stderr)
 def test_owned_transport_keeps_work_tabs_and_original_capture_shape(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);profile=home/'browser-profiles'/'fixture';profile.mkdir(parents=True)
   context={'session':'fixture-session','contextId':'fixture-context','owned':True,'isolated':True,'tab':'A'*32,'idleTimeout':86400,'windowMode':'background','probeSku':'1000000001','profileDir':str(profile),'cdpEndpoint':'http://127.0.0.1:9331'}
   script=r"""const assert=require('node:assert');const {pathToFileURL}=require('node:url');(async()=>{const cfg=JSON.parse(process.argv[1]);const root=process.argv[2];const {Cdp}=require(root+'/mature/diagnosis/scripts/cdp-lib.js');let closed=[];let handlers={};Cdp.connect=async()=>({createTab:async()=> 'B'.repeat(32),listTargets:async()=>[{targetId:'A'.repeat(32),url:'https://item.jd.com/work.html'}],attach:async()=> 'fixture-target',detach:async()=>{},on:(key,fn)=>{handlers[key]=fn;return()=>{}},send:async(method)=>method==='Network.getResponseBody'?{body:JSON.stringify({skuHeadVO:{skuId:'1000000001'}}),base64Encoded:false}:{},evalRaw:async()=>{},closeTarget:async id=>closed.push(id),navigate:async()=>{},close:()=>{}});const t=await import(pathToFileURL(root+'/mature/collection/scripts/owned_cdp_transport.mjs'));await t.configure(cfg);const owner=new t.Page(cfg.session,cfg.idleTimeout,undefined,'background');const id=await owner.newTab();const page=new t.Page(cfg.session,cfg.idleTimeout,undefined,'background');page.setActivePage(id);await page.startNetworkCapture('pc_detailpage_wareBusiness');handlers['Network.requestWillBeSent|fixture-target']({requestId:'fixture-request',request:{url:'https://api.m.jd.com/?functionId=pc_detailpage_wareBusiness',method:'GET',headers:{'X-Skuid-Param':'fixture','Cookie':'synthetic-never-persisted'}}});handlers['Network.responseReceived|fixture-target']({requestId:'fixture-request',response:{status:200}});await handlers['Network.loadingFinished|fixture-target']({requestId:'fixture-request'});const rows=await page.readNetworkCapture();assert.equal(rows.length,1);assert.equal(rows[0].responseStatus,200);assert.ok(rows[0].responseBody);assert.equal((await page.readNetworkCapture()).length,0);await assert.rejects(owner.closeTab('A'.repeat(32)),/TASK_TAB_NOT_OWNED/);assert.equal(closed.length,0);await owner.closeTab(id);assert.deepEqual(closed,[id]);await t.closeTransport();})().catch(e=>{console.error(e.stack);process.exit(1)});"""
   env=dict(os.environ,HEIDENG_MERCHANT_HOME=str(home))
   result=subprocess.run(['node','-e',script,json.dumps(context),str(ROOT)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=20)
   self.assertEqual(result.returncode,0,result.stderr[-1400:])
if __name__=='__main__':unittest.main()
