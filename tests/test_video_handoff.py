"""Video handoff must not accept caller assertions as technical evidence."""
import tempfile,unittest
from pathlib import Path
from heideng_merchant.safety import SafetyError,atomic_json,file_sha,read_json
from heideng_merchant.workflows import attach_video

class VideoHandoffIntegrityTests(unittest.TestCase):
 def test_spoofed_mp4_and_cover_with_all_review_flags_are_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest=root/'manifest.json';atomic_json(manifest,{'merchantPackageSchemaVersion':1})
   video=root/'existing.mp4';video.write_bytes(b'\x00\x00\x00\x18ftypmp42'+b'not-a-video')
   cover=root/'cover.png';cover.write_bytes(b'not-an-image')
   original=manifest.read_bytes()
   review={'sha256':file_sha(video),'technicalPass':True,'visualPass':True,'voiceConfirmed':True}
   with self.assertRaises(SafetyError):attach_video(manifest,video,cover,review)
   self.assertEqual(manifest.read_bytes(),original)
   self.assertFalse((root/'video').exists())
from unittest.mock import patch
from tests.test_video_probe import structural_mp4,evidence
from tests.material_fixtures import png

class ReviewedVideoHandoffTests(unittest.TestCase):
 def setup_files(self,root):
  manifest=root/'manifest.json';atomic_json(manifest,{'merchantPackageSchemaVersion':1,'sourceProduct':{'title':'synthetic item'}})
  video=root/'clip.mp4';video.write_bytes(structural_mp4());cover=root/'cover.png';cover.write_bytes(png())
  return manifest,video,cover
 def mock_checks(self,video,cover):
  return patch('heideng_merchant.video_handoff.probe_video',return_value=evidence(video.read_bytes())),patch('heideng_merchant.video_handoff.probe_video_cover',return_value={'sha256':file_sha(cover),'bytes':cover.stat().st_size,'format':'PNG','width':2,'height':2,'frames':1})
 def test_independent_decode_not_caller_technical_flag_controls_technical_pass(self):
  from heideng_merchant.video_handoff import listing_fingerprint
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest,video,cover=self.setup_files(root);checks=self.mock_checks(video,cover)
   review={'sha256':file_sha(video),'coverSha256':file_sha(cover),'listingFingerprint':listing_fingerprint(read_json(manifest)),'technicalPass':False,'visualPass':True,'voiceConfirmed':True}
   with checks[0],checks[1]:result=attach_video(manifest,video,cover,review,state=root/'state')
   self.assertTrue(result['video']['bindable']);self.assertEqual(result['video']['technicalEvidence']['policy'],'mp4-full-decode-v1');self.assertEqual(result['video']['review']['technical'],'verified-full-decode')
   self.assertEqual(file_sha(root/result['video']['localPath']),file_sha(video));self.assertEqual(file_sha(root/result['video']['coverPath']),file_sha(cover))
 def test_unbound_review_flags_and_undecoded_cover_cannot_make_bindable(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest,video,cover=self.setup_files(root);checks=self.mock_checks(video,cover)
   review={'sha256':file_sha(video),'technicalPass':True,'visualPass':True,'voiceConfirmed':True}
   with checks[0],checks[1]:result=attach_video(manifest,video,cover,review,state=root/'state')
   self.assertFalse(result['video']['bindable']);self.assertEqual(result['video']['review']['visual'],'pending')
 def test_wrong_cover_review_or_secrets_leave_manifest_unchanged(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest,video,cover=self.setup_files(root);original=manifest.read_bytes()
   for review in ({'sha256':file_sha(video),'coverSha256':'0'*64},{'sha256':file_sha(video),'api_key':'synthetic-never-real'}):
    checks=self.mock_checks(video,cover)
    with checks[0],checks[1],self.assertRaises(SafetyError):attach_video(manifest,video,cover,review,state=root/'state')
    self.assertEqual(manifest.read_bytes(),original);self.assertFalse((root/'video').exists())
 def test_cover_changed_during_copy_does_not_publish_manifest(self):
  from heideng_merchant.video_handoff import _checked_copy
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest,video,cover=self.setup_files(root);original=manifest.read_bytes();checks=self.mock_checks(video,cover)
   def change(source,dest,sha,size):
    if Path(source)==cover:cover.write_bytes(b'changed-after-decode')
    return _checked_copy(source,dest,sha,size)
   with checks[0],checks[1],patch('heideng_merchant.video_handoff._checked_copy',side_effect=change),self.assertRaises(SafetyError):attach_video(manifest,video,cover,state=root/'state')
   self.assertEqual(manifest.read_bytes(),original);self.assertFalse((root/'video').exists())
 def test_preflight_rechecks_original_hash_and_listing_identity(self):
  from heideng_merchant.video_handoff import listing_fingerprint,preflight_video
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest,video,cover=self.setup_files(root);checks=self.mock_checks(video,cover)
   review={'sha256':file_sha(video),'coverSha256':file_sha(cover),'listingFingerprint':listing_fingerprint(read_json(manifest)),'visualPass':True,'voiceConfirmed':True}
   with checks[0],checks[1]:result=attach_video(manifest,video,cover,review,state=root/'state')
   result['sourceProduct']['title']='different synthetic product';atomic_json(manifest,result)
   with self.assertRaises(SafetyError):preflight_video(manifest,state=root/'state')

class VideoPartialReviewTests(unittest.TestCase):
 setup_files=ReviewedVideoHandoffTests.setup_files
 mock_checks=ReviewedVideoHandoffTests.mock_checks
 def test_visual_and_voice_status_are_reported_independently(self):
  from heideng_merchant.video_handoff import listing_fingerprint
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest,video,cover=self.setup_files(root);checks=self.mock_checks(video,cover)
   review={'sha256':file_sha(video),'coverSha256':file_sha(cover),'listingFingerprint':listing_fingerprint(read_json(manifest)),'visualPass':True,'voiceConfirmed':False}
   with checks[0],checks[1]:result=attach_video(manifest,video,cover,review,state=root/'state')
   self.assertEqual(result['video']['review']['visual'],'confirmed');self.assertEqual(result['video']['review']['voice'],'pending');self.assertFalse(result['video']['bindable'])

class VideoReviewRaceRegressions(unittest.TestCase):
 setup_files=ReviewedVideoHandoffTests.setup_files
 mock_checks=ReviewedVideoHandoffTests.mock_checks
 def attached(self,root):
  from heideng_merchant.video_handoff import listing_fingerprint
  manifest,video,cover=self.setup_files(root);checks=self.mock_checks(video,cover)
  review={'sha256':file_sha(video),'coverSha256':file_sha(cover),'listingFingerprint':listing_fingerprint(read_json(manifest)),'visualPass':True,'voiceConfirmed':True}
  with checks[0],checks[1]:result=attach_video(manifest,video,cover,review,state=root/'state')
  return manifest,root/result['video']['localPath'],root/result['video']['coverPath'],result
 def test_preflight_rehashes_video_after_cover_probe(self):
  from heideng_merchant.video_handoff import preflight_video
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest,video,cover,result=self.attached(root)
   def change(*a):video.write_bytes(b'changed-during-cover-decode');return result['video']['coverEvidence']
   with patch('heideng_merchant.video_handoff.probe_video',return_value=result['video']['technicalEvidence']),patch('heideng_merchant.video_handoff.probe_video_cover',side_effect=change),self.assertRaises(SafetyError):preflight_video(manifest,state=root/'state')
 def test_preflight_rejects_listing_change_after_snapshot_parse(self):
  import heideng_merchant.video_handoff as h
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest,video,cover,result=self.attached(root);real=h._manifest;calls=0
   def mutate(path):
    nonlocal calls
    calls+=1;snapshot=real(path)
    if calls==2:
     data=read_json(path);data['sourceProduct']['title']='concurrent edit';atomic_json(path,data)
    return snapshot
   with patch.object(h,'_manifest',side_effect=mutate),patch.object(h,'probe_video',return_value=result['video']['technicalEvidence']),patch.object(h,'probe_video_cover',return_value=result['video']['coverEvidence']),self.assertRaises(SafetyError):h.preflight_video(manifest,state=root/'state')
 def test_attach_does_not_restore_listing_from_before_concurrent_edit(self):
  import heideng_merchant.video_handoff as h
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest,video,cover=self.setup_files(root);checks=self.mock_checks(video,cover);real=h._manifest;calls=0
   def mutate(path):
    nonlocal calls
    calls+=1;snapshot=real(path)
    if calls==2:
     data=read_json(path);data['sourceProduct']['title']='concurrent edit';atomic_json(path,data)
    return snapshot
   with patch.object(h,'_manifest',side_effect=mutate),checks[0],checks[1],self.assertRaises(SafetyError):attach_video(manifest,video,cover,state=root/'state')
   self.assertEqual(read_json(manifest)['sourceProduct']['title'],'concurrent edit')
