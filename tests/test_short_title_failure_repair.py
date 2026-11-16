"""Synthetic confirmed-failure originals; no shop/model/network execution."""
import copy,importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.safety import SafetyError,read_json,atomic_json
from heideng_merchant.operations import digest
from tests import test_short_title_health_effects as _health

class FailureRepairTests(unittest.TestCase):
 def setup(self,d):
  c,m,r,b,p,calls,details,_,old=_health.NativeHealthEffectsTests().setup(d)
  raw=p.complete(outcome='失败',reason='rewrite required');wire=b.result_transport.connection_factory;wire.response.body=raw;wire.response.headers[1]=('Content-Length',str(len(raw)));m.collect_results(r['importId'],b)
  problem=[{'improvementDetail':{'troubleCode':'hasShortTitle'}}];c.health[0]['improvementList']=copy.deepcopy(problem);details['101']['improvementList']=copy.deepcopy(problem)
  def invoke(profile,url,**kw):
   out=old(profile,url,**kw)
   if url.endswith('/products/{productId}'):
    for row in out['data']['skuList']:
     if str(row['skuId'])=='101':row['features']['shortTitle']='Old target'
   return out
  c.invoke=invoke
  change=[{'productId':'9','skuId':'101','shortTitle':'Repaired target','review':'passed'}]
  return c,m,r,b,p,details,change
 def api(self,m):self.assertTrue(hasattr(m,'prepare_repair'),'parent-bound confirmed-failure repair is not implemented');return m
 def test_prepare_is_fresh_failed_only_preserves_all_originals_and_parent_approval_not_inherited(self):
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,_,change=self.setup(d)
   try:
    self.api(m);out=m.prepare_repair(r['importId'],b,change);saved=m.repair_record(r['importId'],out['repairPlanId'])
    self.assertEqual(saved['scope']['parentImportId'],r['importId']);self.assertEqual(saved['scope']['parentFingerprint'],r['fingerprint']);self.assertEqual(saved['scope']['changes'][0]['skuId'],'101')
    self.assertTrue(out['currentRepairNeedVerified']);self.assertFalse(out['approvalCurrentlyValid']);self.assertFalse(out['retryAuthorized']);self.assertFalse(out['imported']);self.assertEqual((p.uploads,p.creates),(1,1));self.assertFalse(c.posts)
    rows=m.repair_rows(r['importId'],out['repairPlanId'],view='siblings')['items'];self.assertEqual([v['skuId'] for v in rows],['101','102','1001','9001','9002']);self.assertEqual(len(rows),5)
    self.assertFalse(m.repair_status(r['importId'],out['repairPlanId'])['currentRepairNeedVerified'])
   finally:b.close()
 def test_same_business_content_refreshes_current_reads_but_never_creates_second_child_intent(self):
  with tempfile.TemporaryDirectory() as d:
   _,m,r,b,_,_,change=self.setup(d)
   try:
    self.api(m);one=m.prepare_repair(r['importId'],b,change);two=m.prepare_repair(r['importId'],b,change)
    self.assertEqual(one['repairPlanId'],two['repairPlanId']);self.assertTrue(two['currentRepairNeedVerified']);self.assertEqual(len(list((Path(d)/'short-title-repair-plans'/r['importId']).glob('*.json'))),1)
   finally:b.close()
 def test_success_pending_unknown_and_missing_current_issue_cannot_be_repair_candidates(self):
  for scenario in ('success','pending','healthy','unknown'):
   with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as d:
    c,m,r,b,p,details,change=self.setup(d)
    try:
     self.api(m)
     if scenario in ('success','unknown'):
      raw=p.complete(outcome='成功' if scenario=='success' else '待处理');wire=b.result_transport.connection_factory;wire.response.body=raw;wire.response.headers[1]=('Content-Length',str(len(raw)));m.collect_results(r['importId'],b)
     if scenario=='pending':p.result_dom=['7000000001 处理中 成功：0 失败：0'];m.collect_results(r['importId'],b)
     if scenario=='healthy':c.health[0]['improvementList']=[];details['101']['improvementList']=[]
     with self.assertRaises(SafetyError):m.prepare_repair(r['importId'],b,change)
     self.assertFalse(list((Path(d)/'short-title-repair-plans').rglob('*.json')))
    finally:b.close()
 def test_noop_and_changed_versus_unchanged_sibling_dedup_use_actual_observed_titles(self):
  for title in ('Old target','Old sibling','Ｏｌｄ　ｓｉｂｌｉｎｇ'):
   with self.subTest(title=title),tempfile.TemporaryDirectory() as d:
    _,m,r,b,_,_,change=self.setup(d);change[0]['shortTitle']=title
    try:
     self.api(m)
     with self.assertRaises(SafetyError):m.prepare_repair(r['importId'],b,change)
    finally:b.close()
 def test_new_exact_approval_needs_confirmation_and_live_original_need_and_is_not_retry_authorization(self):
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,details,change=self.setup(d)
   try:
    self.api(m);out=m.prepare_repair(r['importId'],b,change);rid=out['repairPlanId'];fp=out['repairFingerprint']
    for kwargs in ({},{'confirmed':True,'ttl':True},{'confirmed':True,'ttl':29}):
     with self.assertRaises(SafetyError):m.approve_repair(r['importId'],rid,fp,b,**kwargs)
    with self.assertRaises(SafetyError):m.approve_repair(r['importId'],rid,r['fingerprint'],b,confirmed=True)
    approved=m.approve_repair(r['importId'],rid,fp,b,confirmed=True,approval_id='a'*32);self.assertTrue(approved['approvalCurrentlyValid']);self.assertTrue(approved['newApprovalRecorded']);self.assertFalse(approved['retryAuthorized']);self.assertFalse(approved['childImportExecutionAvailable']);self.assertEqual((p.uploads,p.creates),(1,1))
    self.assertTrue(m.repair_status(r['importId'],rid)['approvalCurrentlyValid']);c.health[0]['improvementList']=[];details['101']['improvementList']=[]
    with self.assertRaises(SafetyError):m.approve_repair(r['importId'],rid,fp,b,confirmed=True,approval_id='b'*32)
   finally:b.close()
 def test_guard_loss_current_catalog_drift_or_unobserved_actual_sibling_prevents_plan(self):
  for scenario in ('guard','catalog','actual'):
   with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as d:
    c,m,r,b,_,_,change=self.setup(d)
    try:
     self.api(m)
     if scenario=='guard':b.install_lock.__exit__(None,None,None);b.install_lock=None
     if scenario=='catalog':c.skus[0]['status']=0
     if scenario=='actual':
      old=c.invoke
      def missing(profile,url,**kw):
       out=old(profile,url,**kw)
       if url.endswith('/products/{productId}'):
        for row in out['data']['skuList']:
         if str(row['skuId'])=='102':row['features']={}
       return out
      c.invoke=missing
     with self.assertRaises(SafetyError):m.prepare_repair(r['importId'],b,change)
    finally:b.close()
 def test_missing_tampered_index_and_parent_originals_fail_closed_and_cannot_reprepare(self):
  for scenario in ('index','plan','parent'):
   with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as d:
    _,m,r,b,_,_,change=self.setup(d)
    try:
     self.api(m);out=m.prepare_repair(r['importId'],b,change);rid=out['repairPlanId'];plan=m.repair_record(r['importId'],rid)
     if scenario=='index':next((Path(d)/'short-title-repair-intents'/r['importId']).glob('*.json')).unlink()
     if scenario=='plan':
      file=Path(d)/'short-title-repair-plans'/r['importId']/(rid+'.json');saved=read_json(file);saved['scope']['changes'][0]['skuId']='102';saved['fingerprint']=digest(saved['scope']);atomic_json(file,saved)
     if scenario=='parent':(Path(d)/'short-title-imports'/(r['importId']+'.json')).unlink()
     with self.assertRaises(SafetyError):m.repair_record(r['importId'],rid)
     with self.assertRaises(SafetyError):m.prepare_repair(r['importId'],b,change)
     from heideng_merchant.short_title_import_gate import busy
     try:self.assertTrue(busy(d))
     except SafetyError:pass
     with self.assertRaises(SafetyError):m.plans.ops._assert_resolved(plan['scope']['shop'])
    finally:b.close()


 def test_later_parent_pending_after_current_effect_capture_cannot_borrow_the_old_failure_prefix(self):
  with tempfile.TemporaryDirectory() as d:
   _,m,r,b,p,_,change=self.setup(d)
   try:
    self.api(m);original=m.collect_effects
    def drift(*args,**kwargs):
     value=original(*args,**kwargs);p.result_dom=['7000000001 处理中 成功：0 失败：0'];m.collect_results(r['importId'],b);return value
    with patch.object(m,'collect_effects',side_effect=drift),self.assertRaises(SafetyError):m.prepare_repair(r['importId'],b,change)
   finally:b.close()
 def test_orphan_empty_repair_family_is_not_ignored_by_shop_guard(self):
  from heideng_merchant.short_title_repair import validate_layout
  with tempfile.TemporaryDirectory() as d:
   (Path(d)/'short-title-repair-intents'/('a'*24)).mkdir(parents=True)
   with self.assertRaises(SafetyError):validate_layout(d)
 def test_live_native_pending_not_yet_collected_refuses_new_repair_approval(self):
  with tempfile.TemporaryDirectory() as d:
   _,m,r,b,p,_,change=self.setup(d)
   try:
    out=m.prepare_repair(r['importId'],b,change);p.result_dom=['7000000001 处理中 成功：0 失败：0']
    with self.assertRaises(SafetyError):m.approve_repair(r['importId'],out['repairPlanId'],out['repairFingerprint'],b,confirmed=True,approval_id='c'*32)
    self.assertFalse(list((Path(d)/'short-title-repair-approvals').rglob('*.json')))
   finally:b.close()
 def test_approval_ttl_change_cannot_resurrect_history_validity(self):
  with tempfile.TemporaryDirectory() as d:
   _,m,r,b,_,_,change=self.setup(d)
   try:
    out=m.prepare_repair(r['importId'],b,change);m.approve_repair(r['importId'],out['repairPlanId'],out['repairFingerprint'],b,confirmed=True,ttl=30,approval_id='c'*32);m.clock=lambda:1100
    self.assertFalse(m.repair_status(r['importId'],out['repairPlanId'])['approvalCurrentlyValid'])
    file=Path(d)/'short-title-repair-approvals'/r['importId']/('c'*32+'.json');value=read_json(file);value['expiresAt']=value['approvedAt']+3600;atomic_json(file,value)
    with self.assertRaises(SafetyError):m.repair_status(r['importId'],out['repairPlanId'])
   finally:b.close()
 def test_orphan_approval_quarantines_rows_as_well_as_status(self):
  with tempfile.TemporaryDirectory() as d:
   _,m,r,b,_,_,change=self.setup(d)
   try:
    out=m.prepare_repair(r['importId'],b,change);m.approve_repair(r['importId'],out['repairPlanId'],out['repairFingerprint'],b,confirmed=True,approval_id='c'*32)
    file=Path(d)/'short-title-repair-approvals'/r['importId']/('d'*32+'.json');value=read_json(file.with_name('c'*32+'.json'));value.update(approvalId='d'*32,repairPlanId='e'*24);atomic_json(file,value)
    with self.assertRaises(SafetyError):m.repair_status(r['importId'],out['repairPlanId'])
    with self.assertRaises(SafetyError):m.repair_rows(r['importId'],out['repairPlanId'],view='siblings')
   finally:b.close()
