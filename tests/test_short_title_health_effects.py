"""Original complete native health sources under the real owned synthetic guard."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_short_title_effect_sources as source_fixture
from heideng_merchant.safety import SafetyError,read_json
from heideng_merchant.short_title_contract import source_context
from heideng_merchant.short_title_health_sources import DETAIL_URL
from heideng_merchant.short_title_effect_state import read_log
from heideng_merchant.short_title_import_state import evidence

class NativeHealthEffectsTests(unittest.TestCase):
 def setup(self,d):
  c,m,r,b,p,calls,title=source_fixture.OwnedOriginalEffectReadTests().setup(d)
  plan=m.plans.plan(m.record(r['importId'])['scope']['planId']);_,rows=source_context(d,plan['scope']['auditId']);parents={v['skuId']:v['productId'] for v in rows};details={}
  for row in c.health:
   sku=str(row['skuId'])
   if sku in parents:row['productId']=int(parents[sku]);row['healthScoreId']=int(sku)
   if type(row.get('healthScore')) is not int or not 1<=row['healthScore']<=100:row['healthScore']=80
  for sku,pid in parents.items():
   found=next((v for v in c.health if str(v['skuId'])==sku),None)
   details[sku]={'skuId':int(sku),'productId':int(pid),'healthScoreId':int(sku),'healthScore':found['healthScore'] if found else 80,'improvementList':copy.deepcopy(found['improvementList']) if found else []}
  old=c.invoke;counter=[0]
  def invoke(profile,url,**kw):
   if url==DETAIL_URL:
    counter[0]+=1;calls.append((url,kw.get('method'),copy.deepcopy(kw.get('params'))));return {'code':200,'data':copy.deepcopy(details[str(kw['params']['healthInfoId'])])}
   return old(profile,url,**kw)
  c.invoke=invoke;return c,m,r,b,p,calls,details,counter,invoke
 def observe(self,m,r,b):return m.collect_effects(r['importId'],b)
 def test_dual_list_and_all_five_sibling_details_native_health_not_formal_terminal(self):
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,calls,details,count,old=self.setup(d)
   try:
    out=self.observe(m,r,b);self.assertEqual(out.get('effectEvidenceVersion'),2,'C3 does not yet have native health source evidence')
    self.assertTrue(out['nativeHealthSourcesVerified']);self.assertTrue(out['targetHealthRequirementsSatisfied']);self.assertEqual(count[0],10)
    self.assertEqual([v['skuId'] for v in out['nativeHealthEvidence']['detailsBefore']],list(details));self.assertEqual(len(out['rows']),5)
    self.assertTrue(out['nativeHealthEvidence']['listBefore']['complete']);self.assertTrue(out['nativeHealthEvidence']['listAfter']['complete'])
    for key in ('formalAuditVerified','portalVerified','healthVerified','imported','retryAuthorized'):self.assertFalse(out[key])
    self.assertEqual((p.uploads,p.creates),(1,1));self.assertFalse(c.posts)
   finally:b.close()
 def test_bad_or_absent_detail_keeps_original_and_does_not_infer_health(self):
  for patch in ({'healthScore':None},{'improvementList':None},{'skuId':999},{'productId':999},{'healthScoreId':999}):
   with self.subTest(patch=patch),tempfile.TemporaryDirectory() as d:
    c,m,r,b,p,_,details,count,old=self.setup(d);details['101'].update(patch)
    try:
     out=self.observe(m,r,b);self.assertIn('nativeHealthEvidence',out);self.assertFalse(out['nativeHealthSourcesVerified']);self.assertFalse(out['targetHealthRequirementsSatisfied']);self.assertEqual(len(out['rows']),5)
    finally:b.close()
 def test_offsale_detail_missing_never_drops_scope_or_claims_complete_source(self):
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,_,details,count,old=self.setup(d);details.pop('1001')
   try:
    out=self.observe(m,r,b);self.assertFalse(out.get('nativeHealthSourcesVerified',True));self.assertEqual([v['skuId'] for v in out['nativeHealthEvidence']['detailsAfter']],['101','102','1001','9001','9002'])
    self.assertIsNone(next(v for v in out['nativeHealthEvidence']['detailsAfter'] if v['skuId']=='1001')['detailSha256']);self.assertEqual(len(out['rows']),5)
   finally:b.close()
 def test_health_detail_drift_or_list_detail_conflict_not_verified(self):
  for kind in ('detail-drift','list-conflict'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
    c,m,r,b,p,_,details,count,old=self.setup(d)
    if kind=='list-conflict':details['101']['healthScore']=88
    else:
     def invoke(profile,url,**kw):
      if url==DETAIL_URL and count[0]>=5:details['101']['healthScore']=88
      return old(profile,url,**kw)
     c.invoke=invoke
    try:
     out=self.observe(m,r,b);self.assertFalse(out.get('nativeHealthSourcesVerified',True));self.assertFalse(out['targetHealthRequirementsSatisfied']);self.assertEqual(len(out['rows']),5)
    finally:b.close()
 def test_guard_loss_during_new_detail_read_refuses_new_c3_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,_,details,count,old=self.setup(d)
   def invoke(profile,url,**kw):
    value=old(profile,url,**kw)
    if url==DETAIL_URL and b.install_lock is not None and b.install_lock.acquired:b.install_lock.__exit__(None,None,None)
    return value
   c.invoke=invoke
   try:
    with self.assertRaises(SafetyError):self.observe(m,r,b)
    self.assertFalse(list((Path(d)/'short-title-effect-observations').glob('*/*.json')))
   finally:
    if b.install_lock is not None and not b.install_lock.acquired:b.install_lock=None
    b.close()
 def test_signed_source_data_never_persisted_or_used_as_download(self):
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,_,details,count,old=self.setup(d);details['101']['improvementList']=[{'improvementDetail':{'troubleCode':'hasShortTitle','sourceData':'https://storage.jd.com/synthetic.png?token=DO_NOT_PERSIST_NATIVE_HEALTH'}}]
   try:
    out=self.observe(m,r,b);self.assertFalse(out.get('targetHealthRequirementsSatisfied',True));self.assertNotIn('DO_NOT_PERSIST_NATIVE_HEALTH',json.dumps(out));self.assertNotIn('DO_NOT_PERSIST_NATIVE_HEALTH',''.join(v.read_text(encoding='utf-8-sig') for v in Path(d).rglob('*.json')))
   finally:b.close()
 def test_v1_history_kept_but_new_v2_proof_cannot_be_dropped_on_later_observation(self):
  from heideng_merchant.short_title_effect_state import append_observation
  from heideng_merchant.short_title_verification import observe_original_effects
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,_,details,count,old=self.setup(d)
   try:
    root=m.record(r['importId']);anchors=evidence(d,root)[3];v=observe_original_effects(m,r['importId'],b)
    old_v={k:value for k,value in v.items() if k not in ('effectEvidenceVersion','nativeHealthEvidence','nativeHealthSourcesVerified','targetHealthRequirementsSatisfied')}
    append_observation(d,root,anchors,old_v,1000);path=Path(d)/'short-title-effect-observations'/r['importId']/'000001.json';before=path.read_bytes();out=self.observe(m,r,b)
    self.assertEqual(path.read_bytes(),before);self.assertEqual(read_log(d,root,anchors)[1],2)
    with self.assertRaises(SafetyError):append_observation(d,root,anchors,old_v,1000)
   finally:b.close()

 def test_forged_v2_health_flags_or_scopes_fail_semantic_validation(self):
  from heideng_merchant.short_title_effect_state import append_observation
  from heideng_merchant.short_title_verification import observe_original_effects
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,_,details,count,old=self.setup(d)
   try:
    root=m.record(r['importId']);anchors=evidence(d,root)[3];v=observe_original_effects(m,r['importId'],b)
    variants=[]
    for patch in ({'nativeHealthSourcesVerified':1},{'targetHealthRequirementsSatisfied':1},{'nativeHealthSourcesVerified':False}):variants.append({**copy.deepcopy(v),**patch})
    altered=copy.deepcopy(v);altered['nativeHealthEvidence']['detailsBefore'][0]['productId']='999';variants.append(altered)
    altered=copy.deepcopy(v);altered['nativeHealthEvidence']['detailsBefore'][0]['healthTitleIssue']=True;variants.append(altered)
    altered=copy.deepcopy(v);altered['nativeHealthEvidence']['listBefore']['complete']=False;variants.append(altered)
    altered=copy.deepcopy(v);altered['nativeHealthEvidence']['detailsAfter'].pop();variants.append(altered)
    for altered in variants:
     with self.subTest(keys=list(altered)),self.assertRaises(SafetyError):append_observation(d,root,anchors,altered,1000)
   finally:b.close()
 def test_incomplete_list_or_identity_drift_cannot_be_a_current_complete_health_source(self):
  for mode in ('incomplete-list','identity-loss'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
    c,m,r,b,p,_,details,count,old=self.setup(d)
    if mode=='incomplete-list':
     from heideng_merchant.products import ProductService
     read=ProductService.list_health
     def incomplete(reader,*args,**kwargs):v=read(reader,*args,**kwargs);v['complete']=False;return v
     ctx=patch.object(ProductService,'list_health',incomplete)
    else:
     identity=c.identity
     def invoke(profile,url,**kwargs):
      v=old(profile,url,**kwargs)
      if url==DETAIL_URL:c.identity=lambda profile:{'shopName':'synthetic-other','venderId':'999','shopId':'999','shopType':'POP'}
      return v
     c.invoke=invoke
     from contextlib import nullcontext
     ctx=nullcontext()
    try:
     with ctx:
      if mode=='identity-loss':
       with self.assertRaises(SafetyError):self.observe(m,r,b)
      else:
       v=self.observe(m,r,b);self.assertFalse(v['nativeHealthSourcesVerified']);self.assertFalse(v['targetHealthRequirementsSatisfied'])
    finally:b.close()

 def test_historical_cli_rows_expose_new_proof_separately_from_old_list_fields(self):
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,_,details,count,old=self.setup(d)
   try:
    self.observe(m,r,b);view=m.rows(r['importId'],view='effects');row=view['items'][0]
    self.assertEqual(row.get('nativeHealthEvidenceVersion'),2);self.assertTrue(row['nativeHealthEvidenceHistorical']);self.assertEqual(row['nativeHealthDetailAfter']['skuId'],'101');self.assertFalse(row['nativeHealthDetailAfter']['healthTitleIssue'])
    status=m.status(r['importId']);self.assertTrue(status['nativeHealthSourcesVerified']);self.assertFalse(status['currentNativeHealthSourceVerified']);self.assertFalse(status['healthVerified'])
   finally:b.close()

 def test_agent_guide_and_catalog_do_not_equate_native_health_with_c3_completion(self):
  root=Path(__file__).resolve().parents[1];cap=next(v for v in json.loads((root/'registry.json').read_text(encoding='utf-8-sig'))['capabilities'] if v['id']=='short-titles')
  self.assertTrue(cap.get('nativeHealthDetailReadApi',False));self.assertFalse(cap['C3Complete']);text=(root/cap['nativeHealthReference']).read_text(encoding='utf-8')
  self.assertIn('healthScoreId',text);self.assertIn('targetHealthRequirementsSatisfied',text);self.assertIn('不代表',text)

 def test_v2_legacy_row_and_source_claims_must_match_the_same_native_list(self):
  from heideng_merchant.short_title_effect_state import append_observation
  from heideng_merchant.short_title_verification import observe_original_effects
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,_,details,count,old=self.setup(d)
   try:
    root=m.record(r['importId']);anchors=evidence(d,root)[3];value=observe_original_effects(m,r['importId'],b);variants=[]
    v=copy.deepcopy(value);v['rows'][0]['healthScore']=100;variants.append(v)
    v=copy.deepcopy(value);v['healthSource']['sourcePageHashes']=['0'*64];variants.append(v)
    v=copy.deepcopy(value);v['rows'][0]['healthTitleIssue']=True;v['targetHealthRequirementsSatisfied']=False;variants.append(v)
    for v in variants:
     with self.subTest(score=v['rows'][0]['healthScore']),self.assertRaises(SafetyError):append_observation(d,root,anchors,v,1000)
   finally:b.close()
 def test_signed_source_data_in_list_and_detail_is_projected_before_legacy_parsing(self):
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,_,details,count,old=self.setup(d);signature='https://storage.jd.com/synthetic.png?token=DO_NOT_PERSIST_LIST_HEALTH'
   c.health[1]['improvementList'][0]['improvementDetail']['sourceData']=signature;details['102']['improvementList']=copy.deepcopy(c.health[1]['improvementList'])
   try:
    out=self.observe(m,r,b);self.assertTrue(out['nativeHealthSourcesVerified']);self.assertTrue(out['targetHealthRequirementsSatisfied']);self.assertNotIn('DO_NOT_PERSIST_LIST_HEALTH',json.dumps(out));self.assertNotIn('DO_NOT_PERSIST_LIST_HEALTH',''.join(v.read_text(encoding='utf-8-sig') for v in Path(d).rglob('*.json')))
   finally:b.close()

 def test_old_list_zero_or_fractional_score_facts_not_silently_replaced_by_detail_rules(self):
  for score in (0,55.5):
   with self.subTest(score=score),tempfile.TemporaryDirectory() as d:
    c,m,r,b,p,_,details,count,old=self.setup(d);c.health[0]['healthScore']=score;details['101']['healthScore']=score
    try:
     v=self.observe(m,r,b);self.assertEqual(v['rows'][0]['healthScore'],score);self.assertIsNone(v['nativeHealthEvidence']['detailsAfter'][0]['healthScore']);self.assertFalse(v['nativeHealthSourcesVerified']);self.assertFalse(v['targetHealthRequirementsSatisfied'])
    finally:b.close()

 def test_source_data_url_userinfo_quarantines_whole_effect_even_without_sensitive_words(self):
  with tempfile.TemporaryDirectory() as d:
   c,m,r,b,p,_,details,count,old=self.setup(d);value='https://demo-user:demo-pass@assets.example.invalid/synthetic.png'
   c.health[1]['improvementList'][0]['improvementDetail']['sourceData']=value;details['102']['improvementList']=copy.deepcopy(c.health[1]['improvementList'])
   try:
    with self.assertRaises(SafetyError):self.observe(m,r,b)
    self.assertFalse(list((Path(d)/'short-title-effect-observations').glob('*/*.json')))
   finally:b.close()
