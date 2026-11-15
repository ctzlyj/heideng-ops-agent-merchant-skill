import importlib.util,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.safety import SafetyError,read_json,atomic_json
from tests import video_delivery_fixtures as fixtures,test_video_handoff as handoff

class VideoDeliveryTests(unittest.TestCase):
 def make(self,d):
  self.assertIsNotNone(importlib.util.find_spec('heideng_merchant.video_delivery'),'native upload/save session missing')
  from heideng_merchant.video_delivery import VideoDelivery
  root=Path(d);helper=handoff.ReviewedVideoHandoffTests();manifest,video,cover=helper.setup_files(root);checks=helper.mock_checks(video,cover)
  from heideng_merchant.video_handoff import attach_video,listing_fingerprint
  from heideng_merchant.safety import file_sha
  review={'sha256':file_sha(video),'coverSha256':file_sha(cover),'listingFingerprint':listing_fingerprint(read_json(manifest)),'visualPass':True,'voiceConfirmed':True}
  with checks[0],checks[1]:attach_video(manifest,video,cover,review,state=root/'state')
  client=fixtures.Client(video.stat().st_size);service=VideoDelivery(root/'state',client,transfer=client.transfer);service.ops.connect('merchant-test','synthetic-store','1')
  return root,manifest,client,service
 def probe(self,path,**kw):return {'status':'locally-reviewed','video':read_json(path)['video'],'shopWrites':0,'generationCalls':0}
 def test_preparation_is_read_only_and_exact_parent_approval_required(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):plan=s.prepare('merchant-test',manifest,'video-owned')
   self.assertFalse(c.allocations or c.saves);self.assertFalse(plan['storageVerified'])
   with self.assertRaises(SafetyError):s.execute(plan['sessionId'])
   with self.assertRaises(SafetyError):s.approve(plan['sessionId'],'0'*64,confirmed=True)
   self.assertFalse(c.allocations or c.saves)
 def test_full_allocation_transfer_save_keeps_original_ids_and_distinct_audit(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);result=s.execute(plan['sessionId'])
   self.assertEqual(result['status'],'ready');self.assertTrue(result['storageVerified']);self.assertFalse(result['auditApproved']);self.assertEqual(result['videoId'],'700');self.assertEqual(result['jdVideoId'],'900');self.assertEqual(len(c.allocations),1);self.assertEqual(len(c.saves),1);self.assertEqual(c.saves[0]['zoneVideoDTO']['jdVideoId'],900)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):s.execute(plan['sessionId'])
   self.assertEqual(len(c.allocations),1);self.assertEqual(len(c.saves),1)
   for path in (root/'state').rglob('*.json'):self.assertNotIn(c.secret,path.read_text())
 def test_unknown_each_stage_never_replayed_even_when_remote_target_matches(self):
  for fault in ('allocation-timeout','transfer-timeout','save-timeout'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    root,manifest,c,s=self.make(d)
    with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
     plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);c.fault=fault;result=s.execute(plan['sessionId'])
    self.assertEqual(result['status'],'unknown');counts=(len(c.allocations),len(c.transfers),len(c.saves));c.fault=None;s.status(plan['sessionId'],refresh=True)
    with self.assertRaises(SafetyError):s.execute(plan['sessionId'])
    self.assertEqual(counts,(len(c.allocations),len(c.transfers),len(c.saves)))
 def test_wrong_zone_card_drift_and_expired_approval_block_before_allocation(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    c.fault='zone'
    with self.assertRaises(SafetyError):s.prepare('merchant-test',manifest,'video-owned')
    c.fault=None;plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);c.fault='card'
    with self.assertRaises(SafetyError):s.execute(plan['sessionId'])
    c.fault=None
    with patch('heideng_merchant.video_delivery.time.time',return_value=10**12),self.assertRaises(SafetyError):s.execute(plan['sessionId'])
   self.assertFalse(c.allocations)
 def test_independent_original_receipts_cannot_be_rewritten_or_removed(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);s.execute(plan['sessionId'])
   path=root/'state/video-session-receipts'/plan['sessionId']/'allocate.json';original=read_json(path);original['receipt']['jdVideoId']='999';atomic_json(path,original)
   with self.assertRaises(SafetyError):s.status(plan['sessionId'],refresh=True)
 def test_unknown_video_session_blocks_other_same_shop_business_writes(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);c.fault='transfer-timeout';s.execute(plan['sessionId'])
   with self.assertRaises(SafetyError):s.ops.prepare('merchant-test',{'url':'/rest/sp-product/v0/products','method':'POST','body':{'synthetic':True}})

class VideoDeliveryIntegrityRegressions(unittest.TestCase):
 make=VideoDeliveryTests.make
 probe=VideoDeliveryTests.probe
 def test_rehashed_receipt_and_journal_cannot_forge_original_allocation(self):
  from heideng_merchant.operations import digest
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);s.execute(plan['sessionId'])
   path=root/'state/video-session-receipts'/plan['sessionId']/'allocate.json';record=read_json(path);record['receipt']['jdVideoId']='999';atomic_json(path,record);journal=root/'state/video-sessions'/(plan['sessionId']+'.json');data=read_json(journal);data['receipts']['allocate']=digest(record);atomic_json(journal,data)
   with self.assertRaises(SafetyError):s.status(plan['sessionId'])
 def test_reset_unknown_to_allocated_cannot_renew_grant_for_attempted_transfer(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);c.fault='transfer-timeout';s.execute(plan['sessionId']);journal=root/'state/video-sessions'/(plan['sessionId']+'.json');data=read_json(journal);data['status']='allocated';atomic_json(journal,data);c.fault=None;count=len(c.allocations)
    with self.assertRaises(SafetyError):s.execute(plan['sessionId'])
   self.assertEqual(len(c.allocations),count)
 def test_transfer_receipt_extra_private_fields_are_rejected_not_saved(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d);original=c.transfer
   def transfer(*a,**kw):return {**original(*a,**kw),'uploadUrl':'https://upload.example.test/?grant='+c.secret}
   s.transfer=transfer
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);result=s.execute(plan['sessionId'])
   self.assertEqual(result['status'],'unknown')
   for path in (root/'state').rglob('*.json'):self.assertNotIn(c.secret,path.read_text())
 def test_status_without_refresh_does_not_claim_fresh_storage_verification(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);s.execute(plan['sessionId'])
   result=s.status(plan['sessionId']);self.assertFalse(result['storageVerified']);self.assertTrue(result['metadataHistoricallyVerified'])

class VideoParentApprovalTests(unittest.TestCase):
 make=VideoDeliveryTests.make
 probe=VideoDeliveryTests.probe
 def test_rewriting_parent_deadline_cannot_authorize_upload(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);path=root/'state/video-sessions'/(plan['sessionId']+'.json');data=read_json(path);data['approval']['expiresAt']=10**12;atomic_json(path,data)
    with self.assertRaises(SafetyError):s.execute(plan['sessionId'])
   self.assertFalse(c.allocations)
 def test_known_no_dispatch_can_renew_original_id_without_new_allocation(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);c.fault='before-transfer';result=s.execute(plan['sessionId']);self.assertEqual(result['status'],'allocated');c.fault=None;result=s.execute(plan['sessionId'])
   self.assertEqual(result['status'],'ready');self.assertEqual(len(c.allocations),2);self.assertEqual(c.allocations[1]['jdVideoId'],900);self.assertTrue(c.allocations[1]['breakPointFlag']);self.assertEqual(len(c.saves),1)
 def test_renewed_id_substitution_is_unknown_and_never_transferred(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);c.fault='before-transfer';s.execute(plan['sessionId']);c.fault='wrong-renewed-id';result=s.execute(plan['sessionId'])
   self.assertEqual(result['status'],'unknown');self.assertFalse(c.transfers or c.saves)

class VideoReadbackContractTests(unittest.TestCase):
 make=VideoDeliveryTests.make
 probe=VideoDeliveryTests.probe
 def test_unsupported_readback_schema_is_refused_before_allocating(self):
  from heideng_merchant.video_contract import API
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d);original=c.invoke
   def invoke(profile,url,**kw):
    response=original(profile,url,**kw)
    if kw.get('params',{}).get('apiname')==API['read'][0]:response['data']['inputSchema']['$ref']='#/unsupported'
    return response
   c.invoke=invoke
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe),self.assertRaises(SafetyError):s.prepare('merchant-test',manifest,'video-owned')
   self.assertFalse(c.allocations)
 def test_wrong_native_duration_is_not_storage_verification(self):
  from heideng_merchant.video_contract import VIDEOS
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d);original=c.invoke
   def invoke(profile,url,**kw):
    response=original(profile,url,**kw)
    if url==VIDEOS and kw.get('method','GET')=='GET' and response.get('data'):response['data'][0]['duration']=9
    return response
   c.invoke=invoke
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True)
    with self.assertRaises(SafetyError):s.execute(plan['sessionId'])
   self.assertFalse(s.status(plan['sessionId'])['storageVerified'])

class VideoExistingIdSafetyTests(unittest.TestCase):
 make=VideoDeliveryTests.make
 probe=VideoDeliveryTests.probe
 def test_new_allocation_cannot_reuse_other_saved_session_id_for_different_bytes(self):
  from heideng_merchant.video_transfer import UploadGrant
  from heideng_merchant.video_handoff import listing_fingerprint,attach_video
  import tests.test_video_handoff as helper
  from heideng_merchant.safety import file_sha
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);s.execute(plan['sessionId'])
   new_video=root/'new.mp4';new_video.write_bytes(b'changed synthetic bytes');cover=root/'cover.png';p=root/'other.json';atomic_json(p,{'merchantPackageSchemaVersion':1,'sourceProduct':{'title':'other synthetic'}})
   from tests.test_video_probe import evidence
   info=evidence(new_video.read_bytes());h=helper.ReviewedVideoHandoffTests();checks=h.mock_checks(new_video,cover)
   review={'sha256':file_sha(new_video),'coverSha256':file_sha(cover),'listingFingerprint':listing_fingerprint(read_json(p)),'visualPass':True,'voiceConfirmed':True}
   with checks[0],checks[1]:attach_video(p,new_video,cover,review,state=root/'state')
   c.allocate_video_upload=lambda *a,**kw:UploadGrant(900,'https://upload.example.test/file?grant='+c.secret)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    another=s.prepare('merchant-test',p,'video-owned');s.approve(another['sessionId'],another['fingerprint'],confirmed=True);count=len(c.transfers);result=s.execute(another['sessionId'])
   self.assertEqual(result['status'],'unknown');self.assertEqual(len(c.transfers),count)

class VideoQuarantineReviewRegressions(unittest.TestCase):
 make=VideoDeliveryTests.make
 probe=VideoDeliveryTests.probe
 def test_missing_journal_with_surviving_attempts_blocks_new_session_and_generic_write(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);c.fault='transfer-timeout';s.execute(plan['sessionId']);path=root/'state/video-sessions'/(plan['sessionId']+'.json');path.rename(path.with_suffix('.json.lost'));c.fault=None
    with self.assertRaises(SafetyError):s.prepare('merchant-test',manifest,'video-owned',name='other name')
   with self.assertRaises(SafetyError):s.ops.prepare('merchant-test',{'url':'/rest/sp-product/v0/products','method':'POST','body':{'synthetic':True}})
 def test_empty_fresh_readback_downgrades_ready_without_replaying(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);s.execute(plan['sessionId'])
   c.video=None;result=s.status(plan['sessionId'],refresh=True);self.assertEqual(result['status'],'saved');self.assertFalse(result['storageVerified'])
   with self.assertRaises(SafetyError):s.ops.prepare('merchant-test',{'url':'/rest/sp-product/v0/products','method':'POST','body':{'synthetic':True}})

class VideoAcknowledgedStageRegressions(unittest.TestCase):
 make=VideoDeliveryTests.make
 probe=VideoDeliveryTests.probe
 def test_lost_attempt_cannot_replay_acknowledged_save_from_rewound_journal(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);s.execute(plan['sessionId'])
    journal=root/'state/video-sessions'/(plan['sessionId']+'.json');data=read_json(journal);data['status']='transferred';atomic_json(journal,data)
    (root/'state/video-session-attempts'/plan['sessionId']/'save.json').unlink()
    count=len(c.saves)
    try:s.execute(plan['sessionId'])
    except SafetyError:pass
   self.assertEqual(len(c.saves),count,'acknowledged save must not be dispatched again when its attempt marker is missing')
 def test_lost_attempt_and_journal_receipt_cannot_replay_surviving_original_save(self):
  with tempfile.TemporaryDirectory() as d:
   root,manifest,c,s=self.make(d)
   with patch('heideng_merchant.video_delivery.preflight_video',side_effect=self.probe):
    plan=s.prepare('merchant-test',manifest,'video-owned');s.approve(plan['sessionId'],plan['fingerprint'],confirmed=True);s.execute(plan['sessionId'])
    journal=root/'state/video-sessions'/(plan['sessionId']+'.json');data=read_json(journal);data['status']='transferred';del data['receipts']['save'];atomic_json(journal,data)
    (root/'state/video-session-attempts'/plan['sessionId']/'save.json').unlink()
    count=len(c.saves)
    try:s.execute(plan['sessionId'])
    except SafetyError:pass
   self.assertEqual(len(c.saves),count,'surviving original save evidence must block a second native save')

class VideoOrphanOwnerRegressions(unittest.TestCase):
 def test_every_orphan_record_requires_a_complete_valid_owner(self):
  from heideng_merchant.video_delivery import assert_video_resolved
  shop={'profile':'merchant-test','venderId':'1','shopId':'3','shopName':'synthetic-store'}
  foreign={'profile':'merchant-other','venderId':'2','shopId':'4','shopName':'synthetic-other'}
  invalid=[None,{}, {**foreign,'profile':'default'}, {**foreign,'venderId':''}, {**foreign,'shopId':False}, {**foreign,'shopName':' '}]
  for folder in ('video-session-attempts','video-session-receipts','video-session-anchors','video-session-approvals'):
   for owner in invalid:
    with self.subTest(folder=folder,owner=owner),tempfile.TemporaryDirectory() as d:
     record={'sessionId':'a'*24}
     if owner is not None:record['shop']=owner
     atomic_json(Path(d)/folder/('a'*24)/'synthetic.json',record)
     with self.assertRaises(SafetyError):assert_video_resolved(Path(d),shop)
 def test_ownerless_orphan_is_not_ignored_because_another_record_has_foreign_owner(self):
  from heideng_merchant.video_delivery import assert_video_resolved
  shop={'profile':'merchant-test','venderId':'1','shopId':'3','shopName':'synthetic-store'}
  foreign={'profile':'merchant-other','venderId':'2','shopId':'4','shopName':'synthetic-other'}
  with tempfile.TemporaryDirectory() as d:
   atomic_json(Path(d)/'video-session-attempts'/('a'*24)/'transfer.json',{'sessionId':'a'*24})
   atomic_json(Path(d)/'video-session-receipts'/('a'*24)/'allocate.json',{'sessionId':'a'*24,'shop':foreign})
   with self.assertRaises(SafetyError):assert_video_resolved(Path(d),shop)
 def test_consistent_complete_foreign_orphan_does_not_quarantine_this_shop(self):
  from heideng_merchant.video_delivery import assert_video_resolved
  shop={'profile':'merchant-test','venderId':'1','shopId':'3','shopName':'synthetic-store'}
  foreign={'profile':'merchant-other','venderId':'2','shopId':'4','shopName':'synthetic-other'}
  with tempfile.TemporaryDirectory() as d:
   for folder in ('video-session-attempts','video-session-receipts','video-session-anchors','video-session-approvals'):
    atomic_json(Path(d)/folder/('a'*24)/'synthetic.json',{'sessionId':'a'*24,'shop':foreign})
   assert_video_resolved(Path(d),shop)
