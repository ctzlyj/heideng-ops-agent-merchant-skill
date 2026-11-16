"""Repair commands remain exact-parent originals; synthetic clients and localhost only."""
import copy,tempfile,unittest
from pathlib import Path
from heideng_merchant.safety import SafetyError
from heideng_merchant import short_title_worker_state as original
from heideng_merchant import cli
from tests import test_short_title_worker_state as state_fixture

class RepairCommandTests(unittest.TestCase):
 def test_exact_repair_payloads_stable_acceptance_and_readonly_resume(self):
  self.assertIn('repair-plan',original.ACTIONS,'repair plan has no real original worker command')
  with tempfile.TemporaryDirectory() as d:
   mod,c,j,run,root,old=state_fixture.WorkerStateTests().setup(d)
   command={**old,'action':'repair-plan','changes':[{'productId':'9','skuId':'101','shortTitle':'Repair target','review':'passed'}]}
   import json
   from heideng_merchant.short_title_worker_broker import parse_command
   raw=json.dumps(command).encode()
   try:parsed=parse_command(raw,len(raw))
   except SafetyError:self.fail("new exact repair schema rejected by old six-field HTTP parser")
   self.assertEqual(parsed,command)
   first=mod.accept_command(d,j,run,command);self.assertEqual(mod.accept_command(d,j,run,command),first)
   for changed in ({**command,'changes':[]},{**command,'changes':[{'access_token':'synthetic-test-only'}]},{**command,'confirmed':True}):
    with self.assertRaises(SafetyError):mod.accept_command(d,j,run,changed)
   approval={**old,'requestId':'d'*32,'action':'repair-approve','confirmed':True,'repairPlanId':'1'*24,'repairFingerprint':'2'*64};mod._check_command(d,j,run,approval)
   with self.assertRaises(SafetyError):mod._check_command(d,j,{**run,'resumeReadOnly':True},approval)
   mod._check_command(d,j,{**run,'resumeReadOnly':True},command)
 def test_cli_exposes_owned_repair_plan_and_new_approval_and_history_only_rows(self):
  self.assertIn('repair-plan',original.ACTIONS,'repair CLI must use the owning worker')
  parser=cli.parser();parent=['--worker-id','a'*24,'--import-id','b'*24,'--fingerprint','c'*64]
  plan=parser.parse_args(['short-title-worker-repair-plan',*parent,'--changes','synthetic.json']);self.assertEqual(plan.changes,'synthetic.json')
  approval=parser.parse_args(['short-title-worker-repair-approve',*parent,'--repair-plan-id','d'*24,'--repair-fingerprint','e'*64,'--confirm']);self.assertTrue(approval.confirm)
  rows=parser.parse_args(['short-title-repair-rows','--import-id','b'*24,'--repair-plan-id','d'*24,'--view','siblings']);self.assertEqual(rows.view,'siblings')
 def test_repair_original_folders_are_inside_actual_worker_native_prefix(self):
  self.assertIn('repair-plan',original.ACTIONS,'new repair originals must be protected before exposing the command')
  for folder in ('short-title-repair-plans','short-title-repair-intents','short-title-repair-approvals'):self.assertIn(folder,original.NATIVE_FOLDERS)
 def test_actual_loopback_prepares_and_approves_exact_child_on_original_owner_no_second_native_attempt(self):
  self.assertIn('repair-plan',original.ACTIONS,'repair commands must reach a real owning worker')
  import socket,threading,time
  from unittest.mock import patch
  from tests import test_short_title_worker as core_fixture
  from tests.short_title_result_fixtures import ResultFactory,TransportFactory
  from heideng_merchant.short_title_worker_service import ShortTitleWorkerService
  from heideng_merchant.short_title_result_transport import ResultTransport
  from heideng_merchant.short_title_health_sources import DETAIL_URL
  with tempfile.TemporaryDirectory() as d:
   w,c,j,run,source,_=core_fixture.WorkerLifecycleTests().make(d);native=ResultFactory(d);w.import_factory=lambda:native;wire=TransportFactory();owner=threading.get_ident();native_threads=[];errors=[];outputs=[]
   parents={str(row['skuId']):str(row['productId']) for row in c.skus if row['productId'] in (9,10)}
   for row in c.health:row['healthScore']=80;row['healthScoreId']=row['skuId']
   old=c.invoke
   def invoke(profile,url,**kw):
    native_threads.append(threading.get_ident())
    if url==DETAIL_URL:
     sku=str(kw['params']['healthInfoId']);row=next((x for x in c.health if str(x['skuId'])==sku),None);return {'code':200,'data':{'productId':int(parents[sku]),'skuId':int(sku),'healthScoreId':int(sku),'healthScore':80,'improvementList':copy.deepcopy(row['improvementList']) if row else []}}
    out=old(profile,url,**kw)
    if url.endswith('/products/{productId}'):
     for row in out['data']['skuList']:row['features']={'shortTitle':'Old target' if str(row['skuId'])=='101' else 'Old sibling '+str(row['skuId'])}
    return out
   c.invoke=invoke;service=ShortTitleWorkerService(d,client=c,runtime_verifier=w.runtime_verifier,startup_wait=0)
   def complete(rid):
    until=time.monotonic()+30
    while time.monotonic()<until:
     try:
      out=service.command_status(j['workerId'],rid)
      if out['status']=='completed':return out
     except SafetyError:pass
     time.sleep(.01)
    raise AssertionError('original repair command did not complete')
   def sender():
    try:
     until=time.monotonic()+30
     while time.monotonic()<until:
      try:out=service.status(j['workerId'])
      except SafetyError:out={}
      if out.get('ready') and out.get('importId'):break
      time.sleep(.01)
     else:raise AssertionError('original worker not ready')
     root=original.read_link(d,j);args={'import_id':root['importId'],'fingerprint':root['fingerprint']}
     service.command(j['workerId'],'approve',confirmed=True,request_id='a'*32,**args);complete('a'*32)
     service.command(j['workerId'],'execute',request_id='b'*32,**args);complete('b'*32)
     raw=native.driver.context.page.complete(outcome='失败',reason='rewrite required');wire.response.body=raw;wire.response.headers[1]=('Content-Length',str(len(raw)));w.browser.result_transport=ResultTransport(resolver=wire.resolver,connection_factory=wire,clock=lambda:1000)
     service.command(j['workerId'],'results',request_id='c'*32,**args);complete('c'*32)
     changes=[{'productId':'9','skuId':'101','shortTitle':'Repaired target','review':'passed'}]
     first=service.command(j['workerId'],'repair-plan',changes=changes,request_id='d'*32,**args);planned=complete('d'*32);outputs.append(planned)
     repeat=service.command(j['workerId'],'repair-plan',changes=changes,request_id='d'*32,**args);self.assertEqual(repeat['status'],'completed');self.assertEqual(first['requestId'],repeat['requestId'])
     plan=planned['result'];self.assertTrue(plan['currentRepairNeedVerified']);self.assertFalse(plan['approvalCurrentlyValid'])
     service.command(j['workerId'],'repair-approve',repair_id=plan['repairPlanId'],repair_fingerprint=plan['repairFingerprint'],confirmed=True,request_id='e'*32,**args);outputs.append(complete('e'*32))
     service.command(j['workerId'],'stop',request_id='f'*32)
    except BaseException as error:errors.append(error)
    finally:
     until=time.monotonic()+5
     while w.broker is None and time.monotonic()<until:time.sleep(.01)
     if w.broker is not None:w.broker.stop_requested.set()
   connect=socket.create_connection
   def local_only(address,*args,**kw):
    if address[0]!='127.0.0.1':raise AssertionError('external network forbidden')
    return connect(address,*args,**kw)
   thread=threading.Thread(target=sender)
   with patch('socket.create_connection',side_effect=local_only):
    thread.start();out=w.run();thread.join(timeout=40)
   self.assertFalse(thread.is_alive())
   if errors:raise errors[0]
   self.assertEqual(out['status'],'closed');self.assertEqual(set(native_threads),{owner});self.assertEqual((native.driver.context.page.uploads,native.driver.context.page.creates),(1,1));self.assertFalse(c.posts);self.assertEqual(len(outputs),2)
   approved=outputs[1]['result'];self.assertTrue(approved['approvalCurrentlyValid']);self.assertTrue(approved['newApprovalRecorded']);self.assertFalse(approved['retryAuthorized']);self.assertFalse(approved['childImportExecutionAvailable'])
   self.assertEqual(len(list((Path(d)/'short-title-repair-plans').rglob('*.json'))),1)
   next((Path(d)/'short-title-repair-plans').rglob('*.json')).unlink()
   with self.assertRaises(SafetyError):original.read_runs(d,j)

 def test_agent_cli_loads_only_changes_value_not_the_file_hash_tuple_and_catalog_documents_new_scope(self):
  import json
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   file=Path(d)/'changes.json';changes=[{'productId':'9','skuId':'101','shortTitle':'Repair target','review':'passed'}];file.write_text(json.dumps(changes),encoding='utf-8')
   args=cli.parser().parse_args(['--home',d,'short-title-worker-repair-plan','--worker-id','a'*24,'--import-id','b'*24,'--fingerprint','c'*64,'--changes',str(file)])
   with patch('heideng_merchant.short_title_worker_service.ShortTitleWorkerService') as service:
    service.return_value.command.return_value={'status':'synthetic-only'};cli.run(args);self.assertEqual(service.return_value.command.call_args.kwargs['changes'],changes)
  root=Path(__file__).resolve().parents[1];catalog=json.loads((root/'registry.json').read_text(encoding='utf-8'));cap=next(row for row in catalog['capabilities'] if row['id']=='short-titles')
  self.assertTrue(cap.get('verifiedFailureRepairPlanningApi'));self.assertFalse(cap.get('verifiedFailureChildImportExecutionApi',True));self.assertEqual(cap.get('repairReference'),'references/native-short-title-repair.md');self.assertIn('native-short-title-repair.md',(root/'SKILL.md').read_text(encoding='utf-8'))
