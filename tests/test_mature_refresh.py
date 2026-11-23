"""Whole-shop refresh source and external-boundary tests; no live writes/model calls."""
from tests.fee_consent import isolated_fees, signed_fixture
import importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT/'mature/refresh'
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
class MatureRefreshTests(unittest.TestCase):
 def setUp(self):
  self.paths=list(sys.path);sys.path.insert(0,str(SOURCE/'scripts'));self.names=('_common','no_window','jdo_listing_mvp','source_pricing','component_rounded_pricing','image_patch_update','detail_patch_update');self.saved={x:sys.modules.pop(x,None) for x in self.names}
 def tearDown(self):
  sys.path[:]=self.paths
  for n in self.names:
   sys.modules.pop(n,None)
   if self.saved[n] is not None:sys.modules[n]=self.saved[n]
 def test_registered_actual_refresh_source_not_private_sdk(self):
  from heideng_merchant.mature_runtime import source_path
  path,meta=source_path('image-refresh');self.assertEqual(path,SOURCE/'scripts/new_job.py');self.assertEqual(meta['upstreamCommit'],'8a2f3df185562b1f2f27859a90080d19b2f259cf');self.assertFalse(any(n.startswith('vendor/') for n in meta['files']))
 def test_common_uses_packaged_mature_mover_not_personal_skills(self):
  common=load('_common',SOURCE/'scripts/_common.py')
  with patch.dict(os.environ,{'JDO_MOVER_SKILL':'unrelated-personal-skill','JOYER_SKILL_ROOT':'unrelated-company-sdk'}):
   self.assertEqual(common.jdo_scripts_dir(),ROOT/'mature/listing/scripts')
 def test_registered_key_lookup_does_not_read_company_or_user_registry(self):
  common=load('_common',SOURCE/'scripts/_common.py')
  with patch.dict(os.environ,{'JD_LLM_API_KEY':'fixture-company-marker','GPT_IMAGE2_API_KEY':'fixture-company-marker'},clear=True):self.assertEqual(common.resolve_api_key(),'')
 def test_existing_detail_src_only_rewrite_preserves_other_html(self):
  common=load('_common',SOURCE/'scripts/_common.py')
  html='<p data-note="keep">Original</p><img src="https://img.example/one.jpg"><img src="https://img.example/two.jpg">'
  result,count=common.rewrite_detail_html(html,{'https://img.example/one.jpg':'https://img.example/new.jpg'})
  self.assertEqual(count,1)
  self.assertEqual(result,html.replace('https://img.example/one.jpg','https://img.example/new.jpg'))
 def test_external_image_edit_uses_selected_model_once(self):
  common=load('_common',SOURCE/'scripts/_common.py');gen=load('merchant_refresh_generate',SOURCE/'scripts/generate.py')
  from heideng_merchant.mature_image import MerchantImageClient
  from heideng_merchant.safety import SafetyError
  with tempfile.TemporaryDirectory() as d:
   sources=Path(d);(sources/'fixture.img').write_bytes(b'not-opened-by-fixture')
   with patch.object(MerchantImageClient,'edit',side_effect=SafetyError('unknown-image-response')) as edit:
    client=gen.PinnedClient('gpt-image-2.5','offline-fixture-not-a-secret',1)
    with self.assertRaises(SafetyError):
     client.edit_image(prompt='fixture',images=[sources/'fixture.img'],size='1024x1024')
  self.assertEqual(edit.call_count,1)
 @isolated_fees
 def test_unknown_first_image_keeps_existing_ledger_and_is_not_replayed(self):
  common=load('_common',SOURCE/'scripts/_common.py');gen=load('merchant_refresh_generate',SOURCE/'scripts/generate.py')
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_LTS4AI_API_KEY':'offline-fixture-not-a-secret'}):
   from PIL import Image
   root=Path(d);(root/'sources').mkdir();Image.new('RGB',(10,10)).save(root/'sources/fixture.img',format='JPEG')
   common.save_json(root/'job.json',{'profile':'fixture-profile','venderId':12345,'shopName':'fixture-shop','productIds':[1001]})
   common.save_json(root/'plan-batch.json',{'tasks':{'fixture':{'key':'fixture','productId':1001,'prompt':'fixture'}},'products':[]})
   common.save_json(root/'host-prompts.json',{'fixture':'逐图设计'})
   gen.main(['generate.py',str(root),'--quote-only'])
   quote=common.load_json(root/'image-quote.json')
   self.assertEqual(quote['designs']['fixture']['prompt'],'逐图设计')
   common.save_json(root/'fee-approval.json',signed_fixture({**quote,'approvalRef':'test-message','billing':'requests','maxRequests':1}))
   with patch.object(gen.PinnedClient,'edit_image',side_effect=TimeoutError('unknown-first-output')) as probe:
    with self.assertRaises(SystemExit):gen.main(['generate.py',str(root)])
    self.assertEqual(common.load_json(root/'internal-generation.json')['fixture']['status'],'unknown')
    with self.assertRaises(SystemExit):gen.main(['generate.py',str(root)])
    self.assertEqual(probe.call_count,1)
 def test_orchestrator_does_not_auto_restart_failed_paid_step(self):
  common=load('_common',SOURCE/'scripts/_common.py');runall=load('merchant_refresh_runall',SOURCE/'scripts/run_all.py')
  with tempfile.TemporaryDirectory() as d,patch.object(runall,'run_step',return_value=(1,1.0,'fixture unknown output')) as step,patch.object(runall.time,'sleep',side_effect=AssertionError('no paid-step retry')):
   code=runall.main(['run_all.py',d,'--steps','generate','--retries','3'])
  self.assertEqual(code,1);self.assertEqual(step.call_count,1)
 def test_new_job_retains_original_scope_and_never_overwrites(self):
  new=load('merchant_refresh_new_job',SOURCE/'scripts/new_job.py')
  with tempfile.TemporaryDirectory() as d:
   argv=['new_job.py',d,'--profile','fixture-profile','--vender-id','12345','--shop-name','fixture-shop','--products','1001,1002','--scope','main']
   new.main(argv);record=json.loads((Path(d)/'job.json').read_text(encoding='utf-8'));self.assertEqual(record['productIds'],[1001,1002]);self.assertFalse(record['detailWrite'])
   with self.assertRaises(SystemExit):new.main(argv)

 def test_upload_unknown_result_is_not_replayed_after_restart(self):
  from unittest.mock import Mock
  from PIL import Image
  common=load('_common',SOURCE/'scripts/_common.py')
  upload=load('merchant_refresh_upload',SOURCE/'scripts/upload.py')
  with tempfile.TemporaryDirectory() as d:
   run=Path(d)
   common.save_json(run/'job.json',{'profile':'fixture','venderId':15,'shopName':'fixture','productIds':[41]})
   common.save_json(run/'plan-batch.json',{'tasks':{'blue':{'productId':41}}})
   common.save_json(run/'internal-generation.json',{'blue':{'status':'succeeded'}})
   (run/'generated').mkdir()
   Image.new('RGB',(40,40),'blue').save(run/'generated/blue.png')
   api=Mock()
   api.get.side_effect=lambda skill,url,*args: {'data':[{'zoneType':1,'zoneId':15}]} if url.endswith('media-zones') else {'data':[{'status':1,'categoryId':2}]}
   api.upload.side_effect=TimeoutError('response missing')
   with patch.object(common,'connect',return_value=api),patch.object(common,'verify_identity'):
    with self.assertRaises(SystemExit):upload.main(['upload.py',d])
    self.assertEqual(common.load_json(run/'uploads.json')['blue']['status'],'unknown')
    with self.assertRaisesRegex(RuntimeError,'原素材上传回执'):upload.main(['upload.py',d])
    api.upload.assert_called_once()

 def test_revised_source_does_not_reuse_old_url_or_stale_converted_file(self):
  from hashlib import sha256
  from unittest.mock import Mock
  from PIL import Image
  common=load('_common',SOURCE/'scripts/_common.py')
  upload=load('merchant_refresh_upload',SOURCE/'scripts/upload.py')
  with tempfile.TemporaryDirectory() as d:
   run=Path(d); (run/'generated').mkdir()
   common.save_json(run/'job.json',{'profile':'fixture','venderId':15,'shopName':'fixture','productIds':[41]})
   common.save_json(run/'plan-batch.json',{'tasks':{'blue':{'productId':41}}})
   common.save_json(run/'internal-generation.json',{'blue':{'status':'succeeded'}})
   source=run/'generated/blue.png'; old=Image.new('RGB',(64,64),'red'); old.save(source,compress_level=0)
   old.save(source.with_suffix('.upload.jpg'),format='JPEG')
   orig_hash=sha256(source.read_bytes()).hexdigest()
   common.save_json(run/'uploads.json',{'blue':{'status':'succeeded','imgUrl':'old','sha256':orig_hash}})
   api=Mock()
   sent=[]
   def accept(zone,category,path):
    sent.append(sha256(path.read_bytes()).hexdigest())
    with Image.open(path) as im:self.assertGreater(im.getpixel((0,0))[2],200)
    return {'imgUrl':'new'}
   api.upload.side_effect=accept
   with patch.object(common,'connect',return_value=api),patch.object(common,'verify_identity'),patch.object(upload,'media_space',return_value=('zone',2)):
    upload.main(['upload.py',d])  # Historical unconverted input digest is sufficient.
    api.upload.assert_not_called()
    Image.new('RGB',(64,64),'blue').save(source,compress_level=0)
    with patch.object(upload,'LIMIT',1024):
     with self.assertRaisesRegex(RuntimeError,'实际上传文件'):upload.main(['upload.py',d])
     api.upload.assert_not_called()
     upload.main(['upload.py',d,'--replace-changed-images'])
     result=common.load_json(run/'uploads.json')['blue']
     self.assertEqual(result['previous'][0]['imgUrl'],'old')
     self.assertEqual(result['sha256'],sha256(source.read_bytes()).hexdigest())
     self.assertEqual(result['uploadSha256'],sent[0])
     upload.main(['upload.py',d])
     api.upload.assert_called_once()

 def test_receipt_verifier_compares_each_approved_slot_and_preserves_reused_urls_elsewhere(self):
  from copy import deepcopy
  from tests.test_gallery_patch import detail
  load('_common',SOURCE/'scripts/_common.py')
  verify=load('merchant_refresh_verify',SOURCE/'scripts/verify.py')
  before=detail(); after=deepcopy(before)
  for group in after['material']['mainImages']:
   group['imageInfoList'][0]['imgUrl']='new'
  product={'productId':41,'title':'test','positions':[{'key':'asset','group':'blue','position':1,'url':'shared'}]}
  args=(product,{'positionFilter':[1]}, {}, {'asset':{'status':'succeeded','imgUrl':'new'}},0,None)
  self.assertTrue(verify.evaluate_product(before,after,*args)['ok'])
  after['material']['mainImages'][0]['imageInfoList'][2]['imgUrl']='new'
  self.assertFalse(verify.evaluate_product(before,after,*args)['ok'])
if __name__=='__main__':unittest.main()
