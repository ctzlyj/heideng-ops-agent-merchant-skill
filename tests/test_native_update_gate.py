"""Synthetic original sessions at the real installation and recovery boundaries."""
import json,copy,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from tests import test_distribution as distribution_tests,test_video_delivery as delivery_tests
from heideng_merchant import distribution
from heideng_merchant.safety import SafetyError,read_json,atomic_json,file_sha
from heideng_merchant.updates import ReleaseUpdates

class NativeVideoUpdateGateTests(unittest.TestCase):
 setUp=distribution_tests.DistributionTests.setUp
 tearDown=distribution_tests.DistributionTests.tearDown
 bundle=distribution_tests.DistributionTests.bundle
 install=distribution_tests.DistributionTests.install
 def session(self,fault=None):
  h=delivery_tests.VideoDeliveryTests();root,manifest,c,s=h.make(self.root)
  with patch('heideng_merchant.video_delivery.preflight_video',side_effect=h.probe):
   p=s.prepare('merchant-test',manifest,'video-owned');s.approve(p['sessionId'],p['fingerprint'],confirmed=True);c.fault=fault;r=s.execute(p['sessionId'])
  return p,c,s,r
 def recovery(self):
  stage=self.target.parent/('.heideng-ops-agent-merchant.stage-'+uuid.uuid4().hex);backup=self.target.parent/('.heideng-ops-agent-merchant.backup-'+uuid.uuid4().hex);stage.mkdir();(stage/'marker').write_text('preserve pending recovery');atomic_json(self.state/'install-journal.json',{'target':str(self.target),'stage':str(stage),'backup':str(backup)});return stage
 def test_original_video_unknown_and_allocated_states_block_updates(self):
  for fault in ('allocation-timeout','transfer-timeout','save-timeout','before-transfer'):
   with self.subTest(fault=fault):
    self.tearDown();self.setUp();p,c,s,r=self.session(fault);self.assertIn(r['status'],('unknown','allocated'));self.assertTrue(distribution.busy(self.state))
 def test_known_ready_with_complete_original_records_is_idle(self):
  p,c,s,r=self.session();self.assertEqual(r['status'],'ready');self.assertFalse(distribution.busy(self.state))
 def test_missing_journal_with_any_original_evidence_cannot_clear_busy(self):
  p,c,s,r=self.session('transfer-timeout');(self.state/'video-sessions'/(p['sessionId']+'.json')).unlink();self.assertTrue(distribution.busy(self.state))
 def test_orphan_evidence_and_malformed_terminal_records_fail_closed(self):
  p,c,s,r=self.session();journal=self.state/'video-sessions'/(p['sessionId']+'.json');original=read_json(journal)
  for status in ('unreviewed-terminal',None,[]):
   with self.subTest(status=status):value=copy.deepcopy(original);value['status']=status;atomic_json(journal,value);self.assertTrue(distribution.busy(self.state))
 def test_ready_without_original_approval_evidence_is_not_idle(self):
  p,c,s,r=self.session();journal=self.state/'video-sessions'/(p['sessionId']+'.json');value=read_json(journal);aid=value['approvalId'];value.pop('approval');atomic_json(journal,value);(self.state/'video-session-approvals'/p['sessionId']/(aid+'.json')).unlink();self.assertTrue(distribution.busy(self.state))
 def test_install_unknown_refuses_before_existing_recovery_is_cleaned(self):
  self.install(self.bundle());stage=self.recovery();p,c,s,r=self.session('transfer-timeout');before=(self.state/'install-journal.json').read_bytes()
  with self.assertRaises(SafetyError):self.install(self.bundle('0.2.0'))
  self.assertEqual((self.target/'VERSION').read_text(),'0.1.0');self.assertTrue((stage/'marker').is_file());self.assertEqual((self.state/'install-journal.json').read_bytes(),before)
 def test_rollback_unknown_refuses_before_recovery_or_version_switch(self):
  self.install(self.bundle());self.install(self.bundle('0.2.0'));stage=self.recovery();p,c,s,r=self.session('transfer-timeout')
  with self.assertRaises(SafetyError):distribution.rollback(self.target,self.state)
  self.assertEqual((self.target/'VERSION').read_text(),'0.2.0');self.assertTrue((stage/'marker').is_file());self.assertTrue((self.state/'install-journal.json').exists())
 def test_release_apply_unknown_does_not_download_or_install(self):
  self.install(self.bundle());upgrade=self.bundle('0.2.0');p,c,s,r=self.session('transfer-timeout');calls=[]
  class Result: returncode=0;stderr=''
  def runner(args,**kw):
   calls.append(list(args));reply=Result()
   if args[1]=='api':reply.stdout=json.dumps({'tag_name':'v0.2.0','draft':False,'prerelease':False,'assets':[{'name':'heideng-ops-agent-merchant-0.2.0.zip','size':upgrade.stat().st_size},{'name':'SHA256SUMS','size':100}]})
   else:
    dest=Path(args[args.index('--dir')+1]);name=args[args.index('--pattern')+1]
    (dest/name).write_bytes(upgrade.read_bytes() if name.endswith('.zip') else (file_sha(upgrade)+'  heideng-ops-agent-merchant-0.2.0.zip\n').encode());reply.stdout=''
   return reply
  updates=ReleaseUpdates(self.state,runner=runner)
  with self.assertRaises(SafetyError):updates.apply(self.target)
  self.assertFalse((self.state/'updates').exists());self.assertEqual([a[1] for a in calls],['api']);self.assertEqual((self.target/'VERSION').read_text(),'0.1.0')

class NativeVideoRuntimeAndCancelTests(unittest.TestCase):
 def make(self,d):
  h=delivery_tests.VideoDeliveryTests();root,m,c,s=h.make(d)
  with patch('heideng_merchant.video_delivery.preflight_video',side_effect=h.probe):p=s.prepare('merchant-test',m,'video-owned')
  return root,m,c,s,p
 def test_runtime_version_change_stops_before_allocation(self):
  import heideng_merchant.video_delivery as module
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,p=self.make(d);s.approve(p['sessionId'],p['fingerprint'],confirmed=True)
   with patch.object(module,'VERSION','0.2.0',create=True),patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe),self.assertRaises(SafetyError):s.execute(p['sessionId'])
   self.assertFalse(c.allocations or c.transfers or c.saves)
 def test_local_cancel_requires_unattempted_exact_scope_and_can_rebuild(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,p=self.make(d);self.assertTrue(callable(getattr(s,'cancel',None)),'safe local cancellation is missing')
   with self.assertRaises(SafetyError):s.cancel(p['sessionId'],'0'*64,confirmed=True)
   cancelled=s.cancel(p['sessionId'],p['fingerprint'],confirmed=True);self.assertEqual(cancelled['status'],'cancelled');self.assertFalse(c.allocations);self.assertFalse(distribution.busy(root/'state'))
   with self.assertRaises(SafetyError):s.execute(p['sessionId'])
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe):new=s.prepare('merchant-test',m,'video-owned')
   self.assertNotEqual(new['sessionId'],p['sessionId']);self.assertEqual(new['status'],'prepared');self.assertFalse(c.allocations)
 def test_unknown_cannot_be_cancelled_or_replaced(self):
  with tempfile.TemporaryDirectory() as d:
   root,m,c,s,p=self.make(d);self.assertTrue(callable(getattr(s,'cancel',None)),'safe local cancellation is missing');s.approve(p['sessionId'],p['fingerprint'],confirmed=True);c.fault='transfer-timeout'
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe):s.execute(p['sessionId'])
   with self.assertRaises(SafetyError):s.cancel(p['sessionId'],p['fingerprint'],confirmed=True)
   self.assertTrue(distribution.busy(root/'state'));self.assertEqual(len(c.allocations),1)

class NativeUpdateEvidenceTests(unittest.TestCase):
 def test_binding_completed_is_idle_but_unknown_or_orphaned_evidence_is_not(self):
  from tests import test_video_binding as binding_tests
  with tempfile.TemporaryDirectory() as d:
   h=binding_tests.VideoBindingTests();root,m,c,s,session=h.make(d);plan=h.ready(s,session)
   self.assertFalse(distribution.busy(root/'state'))
   result=h.run_plan(s,plan);self.assertTrue(result['materialFieldsVerified']);self.assertFalse(distribution.busy(root/'state'))
   approval_dir=root/'state'/'video-binding-approvals'/plan['planId']
   approval_path=next(approval_dir.glob('*.json'));original=approval_path.read_bytes();approval_path.write_text('{}')
   self.assertTrue(distribution.busy(root/'state'));approval_path.write_bytes(original)
   marker=next((root/'state'/'video-binding-attempts').glob('*.json'));task=root/'state'/'tasks'/marker.name
   task.unlink();self.assertTrue(distribution.busy(root/'state'))
 def test_unrecognized_or_linked_managed_evidence_cannot_be_ignored(self):
  from heideng_merchant import safety
  for folder in ('video-sessions','video-binding-plans','video-session-attempts','video-binding-intents'):
   with self.subTest(folder=folder),tempfile.TemporaryDirectory() as d:
    state=Path(d);managed=state/folder;managed.mkdir();p=managed/'unrecognized.txt';p.write_text('synthetic')
    self.assertTrue(distribution.busy(state));p.unlink()
    actual=safety.is_linked
    with patch('heideng_merchant.safety.is_linked',side_effect=lambda q: Path(q)==managed or actual(q)):
     self.assertTrue(distribution.busy(state))
 def test_cancelled_proof_loss_edit_and_journal_reset_remain_blocked(self):
  for fault in ('missing','edited','reset','malformed-time'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    h=NativeVideoRuntimeAndCancelTests();root,m,c,s,p=h.make(d);s.cancel(p['sessionId'],p['fingerprint'],confirmed=True)
    proof=root/'state'/'video-session-cancellations'/(p['sessionId']+'.json');journal=root/'state'/'video-sessions'/(p['sessionId']+'.json')
    if fault=='missing':proof.unlink()
    elif fault=='edited':value=read_json(proof);value['cancelledAt']+=1;atomic_json(proof,value)
    elif fault=='malformed-time':
     from heideng_merchant.operations import digest
     value=read_json(proof);value['cancelledAt']='invalid';atomic_json(proof,value);session=read_json(journal);session['cancellationSha256']=digest(value);atomic_json(journal,session)
    else:value=read_json(journal);value['status']='prepared';value.pop('cancellationSha256');atomic_json(journal,value)
    self.assertTrue(distribution.busy(root/'state'))
    with self.assertRaises(SafetyError):s.status(p['sessionId'])
    self.assertFalse(c.allocations or c.transfers or c.saves)
 def test_legacy_complete_can_be_reused_read_only_but_unstarted_cannot_dispatch(self):
  from heideng_merchant.operations import digest
  for complete in (False,True):
   with self.subTest(complete=complete),tempfile.TemporaryDirectory() as d:
    h=NativeVideoRuntimeAndCancelTests();root,m,c,s,p=h.make(d)
    old=root/'state'/'video-sessions'/(p['sessionId']+'.json');value=read_json(old);value['scope'].pop('runtimeVersion');value['scope'].pop('planNonce');value['fingerprint']=digest(value['scope']);value['sessionId']=value['fingerprint'][:24];old.unlink();atomic_json(old.with_name(value['sessionId']+'.json'),value)
    s.approve(value['sessionId'],value['fingerprint'],confirmed=True)
    if complete:
     with patch.object(s,'_check',return_value=__import__('time').time()+900),patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe):s.execute(value['sessionId'])
    with patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe):again=s.prepare('merchant-test',m,'video-owned')
    self.assertEqual(again['sessionId'],value['sessionId']);self.assertEqual(distribution.busy(root/'state'),not complete)
    if complete:self.assertEqual(s.status(value['sessionId'])['status'],'ready');self.assertEqual(len(c.allocations),1)
    else:
     with self.assertRaises(SafetyError):s.execute(value['sessionId'])
     self.assertFalse(c.allocations)
 def test_cancellation_cli_executes_exact_local_guard_without_business_client(self):
  from heideng_merchant import cli
  with tempfile.TemporaryDirectory() as d:
   h=NativeVideoRuntimeAndCancelTests();root,m,c,s,p=h.make(d)
   state=root/'state'
   args=['video-delivery-cancel','--session-id',p['sessionId'],'--fingerprint',p['fingerprint']]
   try:parsed=cli.parser().parse_args(args)
   except SystemExit:self.fail('safe local cancellation has no CLI entry point')
   with patch.dict(__import__('os').environ,{'HEIDENG_MERCHANT_HOME':str(state)}):
    with self.assertRaises(SafetyError):cli.run(parsed)
    result=cli.run(cli.parser().parse_args([*args,'--confirm']));self.assertEqual(result['status'],'cancelled')
   self.assertFalse(c.allocations or c.transfers or c.saves);self.assertFalse(distribution.busy(state))

class NativeUpdateReviewRegressions(unittest.TestCase):
 setUp=distribution_tests.DistributionTests.setUp
 tearDown=distribution_tests.DistributionTests.tearDown
 bundle=distribution_tests.DistributionTests.bundle
 install=distribution_tests.DistributionTests.install
 session=NativeVideoUpdateGateTests.session
 recovery=NativeVideoUpdateGateTests.recovery
 def test_receipt_bearing_prepared_cannot_allow_recovery_and_upgrade(self):
  self.install(self.bundle());p,c,s,r=self.session();c.video['status']=3;s.status(p['sessionId'],refresh=True)
  journal=self.state/'video-sessions'/(p['sessionId']+'.json');value=read_json(journal);self.assertEqual(value['status'],'saved');value['status']='prepared';atomic_json(journal,value)
  stage=self.recovery();before=(self.state/'install-journal.json').read_bytes();self.assertTrue(distribution.busy(self.state))
  with self.assertRaises(SafetyError):self.install(self.bundle('0.2.0'))
  self.assertEqual((self.state/'install-journal.json').read_bytes(),before);self.assertTrue((stage/'marker').is_file());self.assertEqual((self.target/'VERSION').read_text(),'0.1.0')
 def test_unrecognized_original_attempt_prevents_cancellation_or_reallocation(self):
  p,c,s,r=self.session('allocation-timeout');marker=self.state/'video-session-attempts'/p['sessionId']/'allocate.json';other=marker.with_name('allocate-original.json');other.write_bytes(marker.read_bytes());marker.unlink()
  journal=self.state/'video-sessions'/(p['sessionId']+'.json');value=read_json(journal);value['status']='prepared';atomic_json(journal,value)
  with self.assertRaises(SafetyError):s.cancel(p['sessionId'],p['fingerprint'],confirmed=True)
  self.assertTrue(distribution.busy(self.state))
  with patch('heideng_merchant.video_delivery.preflight_video',side_effect=delivery_tests.VideoDeliveryTests().probe),self.assertRaises(SafetyError):s.prepare('merchant-test',value['scope']['manifestPath'],'video-owned')
  self.assertEqual(len(c.allocations),1);self.assertFalse(c.transfers or c.saves)
 def test_self_hashed_but_incomplete_scope_does_not_prove_idle(self):
  from heideng_merchant import VERSION
  from heideng_merchant.operations import digest
  scope={'runtimeVersion':VERSION};fp=digest(scope);atomic_json(self.state/'video-sessions'/(fp[:24]+'.json'),{'sessionId':fp[:24],'fingerprint':fp,'scope':scope,'status':'prepared','receipts':{}})
  self.assertTrue(distribution.busy(self.state))
 def test_additional_incomplete_approval_cannot_be_ignored(self):
  p,c,s,r=self.session();value=read_json(self.state/'video-sessions'/(p['sessionId']+'.json'))
  atomic_json(self.state/'video-session-approvals'/p['sessionId']/('a'*32+'.json'),{'sessionId':p['sessionId'],'fingerprint':p['fingerprint'],'shop':value['scope']['shop']})
  self.assertTrue(distribution.busy(self.state))
 def test_prepared_native_binding_child_requires_parent_and_intent(self):
  from tests import test_video_binding as binding_tests
  h=binding_tests.VideoBindingTests();root,m,c,s,session=h.make(self.root);plan=h.ready(s,session)
  (self.state/'video-binding-plans'/(plan['planId']+'.json')).unlink()
  for p in (self.state/'video-binding-intents').glob('*.json'):p.unlink()
  self.assertTrue(list((self.state/'tasks').glob('*.json')));self.assertTrue(distribution.busy(self.state))

 def test_incomplete_additional_binding_approval_cannot_prove_idle(self):
  from tests import test_video_binding as binding_tests
  h=binding_tests.VideoBindingTests();root,m,c,s,session=h.make(self.root);plan=h.ready(s,session);value=read_json(self.state/'video-binding-plans'/(plan['planId']+'.json'))
  atomic_json(self.state/'video-binding-approvals'/plan['planId']/('a'*32+'.json'),{'planId':plan['planId'],'fingerprint':plan['fingerprint'],'shop':value['scope']['context']['shop']})
  self.assertTrue(distribution.busy(self.state))
 def test_self_hashed_scope_still_requires_complete_decoder_schema(self):
  from heideng_merchant.operations import digest
  h=NativeVideoRuntimeAndCancelTests();root,m,c,s,p=h.make(self.root);old=self.state/'video-sessions'/(p['sessionId']+'.json');value=read_json(old)
  value['scope']['video']['technicalEvidence']={'bytes':value['scope']['video']['technicalEvidence']['bytes']};value['fingerprint']=digest(value['scope']);value['sessionId']=value['fingerprint'][:24];old.unlink();atomic_json(old.with_name(value['sessionId']+'.json'),value)
  self.assertTrue(distribution.busy(self.state))
