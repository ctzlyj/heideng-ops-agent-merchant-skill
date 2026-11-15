import csv,json,tempfile,unittest
from pathlib import Path
from heideng_merchant.workflows import diagnose_rows,compare_exact_specs,prepare_listing,material_audit,package_snapshot,attach_video
from heideng_merchant.safety import SafetyError,file_sha

class WorkflowTests(unittest.TestCase):
 def test_diagnosis_marks_missing_and_does_not_invent(self):
  r=diagnose_rows([{'skuId':'1','revenue':'100','orders':'2','adSpend':'10','adRevenue':'30'},{'skuId':'2','orders':'0','stock':'0'}])
  self.assertEqual(r['metrics']['revenue']['status'],'partial');self.assertEqual(r['metrics']['revenue']['value'],'100')
  self.assertEqual(r['scope'],'uploaded-rows');self.assertIn('stock',r['missingFields']);self.assertTrue(r['issues'])
 def test_diagnosis_rejects_nonfinite(self):
  with self.assertRaises(SafetyError):diagnose_rows([{'skuId':'1','revenue':'NaN'}])
 def test_exact_spec_top10_excludes_other_pack(self):
  spec={'brand':'B','model':'M','weight':'500g'}
  rows=[{'skuId':str(i),'specs':spec,'handPrice':str(i+1),'evidence':'native-sku-context'} for i in range(12)]+[{'skuId':'bad','specs':{**spec,'weight':'1kg'},'handPrice':'0.5','evidence':'native-sku-context'}]
  r=compare_exact_specs(rows,spec);self.assertEqual(len(r['top10']),10);self.assertNotIn('bad',[x['skuId'] for x in r['top10']]);self.assertEqual(r['excludedCount'],1)
 def test_compare_requires_real_price_evidence(self):
  r=compare_exact_specs([{'skuId':'1','specs':{'size':'L'},'handPrice':'10'}],{'size':'L'});self.assertEqual(r['top10'],[])
 def fixture(self,root):
  (root/'photo.jpg').write_bytes(b'\xff\xd8\xff'+b'fake fixture')
  return {'title':'真实实拍商品','categoryId':'12','skus':[{'merchantCode':'A','specs':{'color':'红'},'price':'10','stock':'2'},{'merchantCode':'B','specs':{'color':'蓝'},'price':'11','stock':'3'}],'images':['photo.jpg'],'sellingPoints':['用户给定卖点']}
 def test_listing_preserves_all_skus_and_no_fake_link(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest=prepare_listing(self.fixture(root),root,root/'package')
   self.assertEqual(len(manifest['skus']),2);self.assertNotIn('jdUrl',manifest);self.assertEqual(manifest['source']['kind'],'local-photos');self.assertEqual(manifest['publication']['status'],'not_submitted')
 def test_listing_escape_and_duplicate_sku(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);x=self.fixture(root);x['images']=['../secret']
   with self.assertRaises(SafetyError):prepare_listing(x,root,root/'out')
   x=self.fixture(root);x['skus'][1]['merchantCode']='A'
   with self.assertRaises(SafetyError):prepare_listing(x,root,root/'out')
 def test_material_audit_keeps_every_sku(self):
  r=material_audit([{'spuId':'1','skuId':'a','white':'ok'},{'spuId':'1','skuId':'b'},{'spuId':'2','skuId':'c'}])
  self.assertEqual(r['skuCount'],3);self.assertEqual(r['spuCount'],2);self.assertEqual(r['batches'][0]['spuCount'],2)
 def test_snapshot_requires_sku_order_and_native_price_context(self):
  snapshot={'title':'test','url':'https://item.jd.com/1.html','selectedSkuId':'1','skuOrder':['1','2'],'skus':[{'skuId':'1','handPrice':'10','priceEvidence':'native-sku-context'},{'skuId':'2','handPrice':'11','priceEvidence':'native-sku-context'}],'assets':[]}
  with tempfile.TemporaryDirectory() as d:
   r=package_snapshot(snapshot,Path(d));self.assertEqual(r['skuOrder'],['1','2']);self.assertEqual(r['assetCount'],0)
   snapshot['skuOrder']=['2','1','3']
   with self.assertRaises(SafetyError):package_snapshot(snapshot,Path(d)/'bad')
 def test_video_never_bindable_without_verified_reviews(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest=prepare_listing(self.fixture(root),root,root/'package');video=root/'existing.mp4';video.write_bytes(b'\x00\x00\x00\x18ftypmp42'+b'fixture')
   r=attach_video(root/'package'/'manifest.json',video,None);self.assertFalse(r['video']['bindable']);self.assertEqual(r['video']['origin'],'user-supplied');self.assertEqual(r['video']['sha256'],file_sha(video))

 def test_snapshot_does_not_persist_browser_credentials(self):
  snapshot={'title':'test','url':'https://item.jd.com/1.html','selectedSkuId':'1','skuOrder':['1'],'skus':[{'skuId':'1','handPrice':'10','priceEvidence':'native-sku-context'}],'assets':[],'cookies':'fake-only'}
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(SafetyError):package_snapshot(snapshot,Path(d))
 def test_listing_rejects_credential_payload(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);product=self.fixture(root);product['skus'][0]['access_token']='fake-only'
   with self.assertRaises(SafetyError):prepare_listing(product,root,root/'out')

if __name__=='__main__':unittest.main()

class ListingInputPreservationTests(unittest.TestCase):
 def test_full_original_product_and_single_sku_with_no_sale_dimensions_are_preserved(self):
  from tests.material_fixtures import png
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'photo.png').write_bytes(png());product={'title':'plain single item','categoryId':44207,'brandId':9001,'transportId':'12','attributes':{'origin':'user-provided'},'images':['photo.png'],'skus':[{'merchantCode':'ONLY','specs':{},'price':'30.00','stock':1}]}
   result=prepare_listing(product,root,root/'listing');self.assertEqual(result['sourceProduct'],product);self.assertEqual(result['skus'][0]['specs'],{})
