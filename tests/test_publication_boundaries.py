import copy,json,shutil,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.publication_contract import validation_verdict,PUBLISH,VALIDATION_TTL
from heideng_merchant.operations import Operations
from heideng_merchant.publishing import PublishService
from heideng_merchant.workflows import prepare_listing
from heideng_merchant.safety import SafetyError,atomic_json,read_json
from tests import publish_fixtures as f

class PublicationBoundaryTests(unittest.TestCase):
 def make(self,d):
  c,ops,m,p,sp,a=f.setup(d);return c,ops,PublishService(d,c),m,p,sp,a
 def validate(self,ops,s,m,p,sp,a):
  task=s.plan_validation(f.PROFILE,m,p,sp,a)['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);ops.execute(task['taskId']);return task['taskId']
 def test_all_validation_envelopes_reviewed_before_pass(self):
  for reply,expected in (({'success':True,'unreviewedReport':['rejected'],'data':{}},'unproven'),({'success':True,'data':{'wareKeeperDetectResultList':[],'data':{'wareKeeperDetectResultList':[{'reason':'rejected'}]}}},'failed'),({'success':True,'data':{'wareKeeperDetectResultList':[],'data':{'otherReport':[]}}},'unproven')):
   with self.subTest(reply=reply):self.assertEqual(validation_verdict(reply),expected)
 def test_validation_execution_metadata_must_match_scope(self):
  execution={'transport':'official-source-stdin','officialVersion':'0.3.7'}
  self.assertEqual(validation_verdict({'success':True,'data':{},'_merchantExecution':execution},expected_execution=execution),'passed')
  self.assertEqual(validation_verdict({'success':True,'data':{},'_merchantExecution':execution},expected_execution={'transport':'official-binary'}),'unproven')
  self.assertEqual(validation_verdict({'success':True,'data':{},'_merchantExecution':execution}),'unproven')
 def test_nested_rejection_cannot_reach_publication_post(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);c.validation_reply={'success':True,'data':{'wareKeeperDetectResultList':[],'data':{'wareKeeperDetectResultList':[{'reason':'rejected'}]}}};v=self.validate(ops,s,m,p,sp,a)
   with self.assertRaises(SafetyError):s.plan_publish(v)
   self.assertEqual(c.publish_posts,0)
 def test_html_comments_declarations_pi_and_mismatched_tags_refused(self):
  for html in ('<div><!--><script>alert(1)</script>--><img src="https://img14.360buyimg.com/imgzone/jfs/t1/1/synthetic.png"></div>','<div><!-- ordinary comment --></div>','<![CDATA[foo]]>','<?xml version="1"?>','<div></span>'):
   with self.subTest(html=html),tempfile.TemporaryDirectory() as d:
    c,ops,s,m,p,sp,a=self.make(d);p[-2]['value'][0]['properties'][0]['value']=html
    with self.assertRaises(SafetyError):s.plan_validation(f.PROFILE,m,p,sp,a)
    self.assertEqual(c.validation_posts,0)
 def test_canonical_html_is_approved_not_mutated_at_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);p[-2]['value'][0]['properties'][0]['value']="<DIV><img src='https://img14.360buyimg.com/imgzone/jfs/t1/1/synthetic.png' alt='a&b'/><BR/></DIV>"
   v=self.validate(ops,s,m,p,sp,a);body=ops.task(v)['scope']['operation']['body'];html=json.loads(body['schema'])[-2]['value'][0]['properties'][0]['value']
   self.assertEqual(html,'<div><img alt="a&amp;b" src="https://img14.360buyimg.com/imgzone/jfs/t1/1/synthetic.png"><br></div>')
   pub=s.plan_publish(v)['task'];self.assertEqual(pub['scope']['operation']['body'],body)
   ops.approve(pub['taskId'],pub['fingerprint'],confirmed=True);ops.execute(pub['taskId']);self.assertEqual(c.publish_posts,1)
 def test_copied_package_cannot_create_a_second_product(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);v=self.validate(ops,s,m,p,sp,a);pub=s.plan_publish(v)['task'];ops.approve(pub['taskId'],pub['fingerprint'],confirmed=True);ops.execute(pub['taskId'])
   clone=Path(d)/'copied';shutil.copytree(m.parent,clone);v2=self.validate(ops,s,clone/'manifest.json',p,sp,a);again=s.plan_publish(v2)['task']
   self.assertEqual(again['taskId'],pub['taskId']);self.assertEqual(c.publish_posts,1)
 def test_copied_unstarted_publication_supersedes_original(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);v=self.validate(ops,s,m,p,sp,a);old=s.plan_publish(v)['task'];ops.approve(old['taskId'],old['fingerprint'],confirmed=True)
   clone=Path(d)/'copied';shutil.copytree(m.parent,clone);v2=self.validate(ops,s,clone/'manifest.json',p,sp,a);new=s.plan_publish(v2)['task']
   self.assertNotEqual(old['taskId'],new['taskId']);self.assertEqual(ops.task(old['taskId'])['status'],'superseded')
   with self.assertRaises(SafetyError):ops.execute(old['taskId'])
 def test_persisted_creation_intent_not_validation_nonce(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);manifest=read_json(m);intent=manifest['publication']['intentId']
   task=s.plan_validation(f.PROFILE,m,p,sp,a)['task'];proof=task['scope']['nativeListingInput'];self.assertEqual(proof['publicationIntentId'],intent);self.assertNotEqual(proof['intentId'],intent)
   # Explicitly preparing another package is a new intent, even with identical input.
   other=prepare_listing(manifest['sourceProduct'],Path(d)/'photos',Path(d)/'new-product');self.assertNotEqual(other['publication']['intentId'],intent)
 def test_publication_validation_rechecked_after_transport_preflight(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);execution={'transport':'official-source-stdin','officialVersion':'0.3.7'};c.plan_execution=lambda *args,**kw:execution;invoke=c.invoke
   def call(profile,url,**kw):
    result=invoke(profile,url,**kw);return {**result,'_merchantExecution':execution}
   c.invoke=call;v=self.validate(ops,s,m,p,sp,a);pub=s.plan_publish(v)['task'];ops.approve(pub['taskId'],pub['fingerprint'],confirmed=True);now=[ops.task(v)['finishedAt']+590]
   def slow(op,**kw):
    if op['url']==PUBLISH:now[0]+=15
    return execution
   c.plan_execution=slow
   with patch('time.time',side_effect=lambda:now[0]):
    with self.assertRaises(SafetyError):ops.execute(pub['taskId'])
   self.assertEqual(c.publish_posts,0);self.assertEqual(ops.task(pub['taskId'])['status'],'prepared')
 def test_final_transport_deadline_is_minimum_of_both_authorizations(self):
  for ttl in (60,900):
   with self.subTest(ttl=ttl),tempfile.TemporaryDirectory() as d:
    c,ops,s,m,p,sp,a=self.make(d);execution={'transport':'official-source-stdin','officialVersion':'0.3.7'};c.plan_execution=lambda *args,**kw:execution;invoke=c.invoke
    def call(profile,url,**kw):return {**invoke(profile,url,**kw),'_merchantExecution':execution}
    c.invoke=call;v=self.validate(ops,s,m,p,sp,a);pub=s.plan_publish(v)['task'];approved=ops.approve(pub['taskId'],pub['fingerprint'],confirmed=True,ttl_seconds=ttl);ops.execute(pub['taskId'])
    kw=next(kw for url,kw in reversed(c.calls) if url==PUBLISH)
    self.assertEqual(kw['authorization_expires_at'],min(approved['approval']['expiresAt'],ops.task(v)['finishedAt']+VALIDATION_TTL))

 def test_direct_task_cannot_bypass_canonical_safe_html(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,s,m,p,sp,a=self.make(d);v=self.validate(ops,s,m,p,sp,a);scope=copy.deepcopy(ops.task(v)['scope']);schema=json.loads(scope['operation']['body']['schema'])
   schema[-2]['value'][0]['properties'][0]['value']='<DIV><img src="https://img14.360buyimg.com/imgzone/jfs/t1/1/synthetic.png"></DIV>'
   scope['operation']['url']=PUBLISH;scope['operation']['body']['schema']=json.dumps(schema)
   with self.assertRaises(SafetyError):ops.prepare(f.PROFILE,scope['operation'],listing_input=scope['nativeListingInput'],validated_task_id=v)
   self.assertEqual(c.publish_posts,0)
 def test_legacy_missing_or_changed_publication_intent_refused(self):
  for mode in ('missing','invalid','changed-after-plan'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
    c,ops,s,m,p,sp,a=self.make(d);manifest=read_json(m)
    if mode=='changed-after-plan':
     task=s.plan_validation(f.PROFILE,m,p,sp,a)['task'];ops.approve(task['taskId'],task['fingerprint'],confirmed=True);manifest['publication']['intentId']='0'*32;atomic_json(m,manifest)
     with self.assertRaises(SafetyError):ops.execute(task['taskId'])
    else:
     if mode=='missing':manifest['publication'].pop('intentId')
     else:manifest['publication']['intentId']='not-a-creation-intent'
     atomic_json(m,manifest)
     with self.assertRaises(SafetyError):s.plan_validation(f.PROFILE,m,p,sp,a)
    self.assertEqual(c.validation_posts,0)
