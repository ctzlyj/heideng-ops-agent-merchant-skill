"""Cross-chat delivery reads the acknowledged pixels and a target SKU proven by store records."""
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from heideng_merchant.safety import atomic_json, clean_environment
from heideng_merchant.sample_delivery import target_sku


ROOT = Path(__file__).resolve().parents[1]


class SampleDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.state = self.root/'state'
        self.parent = self.state/'work/listing/collection/run'
        self.sample = self.parent/'.samples/first-view'
        self.store = {'shopId':'701','venderId':'802','shopName':'合成店','profile':'fixture'}
        atomic_json(self.state/'linker/shops.json', {'profiles':{'fixture':dict(self.store,lastVerifiedAt=1)}})
        self.manifest = {'mode':'photo-new-listing','packageId':'the-task','store':self.store,
                         'facts':{'skus':[{'key':'blue','spec':'蓝色/L'}]},'reference':{'sourceSpuId':'81'},
                         'variants':[{'key':'blue','skuId':None}], 'productId':None,'acceptedSamples':{}}
        self.original = self.accept(b'accepted garment image')
        atomic_json(self.parent/'manifest.json', self.manifest)
        atomic_json(self.parent/'state.json', {'status':'SUCCEEDED','productId':'99','itemNumber':'test'})
        self.listing = {'product':{'itemNumber':'test'},'skus':[
            {'skuKey':'red','vendorSku':'R'},{'skuKey':'blue','vendorSku':'B'}]}
        atomic_json(self.parent/'listing.json', self.listing)
        self.remote = {'productInfo':{'productId':99},'skuList':[
            {'skuId':103,'outerId':'B'},{'skuId':104,'outerId':'R'}]}
        atomic_json(self.parent/'.publish/readback-product.json', self.remote)
        atomic_json(self.sample/'manifest.json', {'mode':'photo-new-listing', 'store':self.store,'packageId':'sample-id',
                    'sampleOf':{'packageId':'the-task','imageId':'first-view'},'status':'MATERIAL_PREVIEW'})

    def accept(self, content):
        digest = sha256(content).hexdigest()
        path = f'已接受样张/first-view-{digest}.jpg'
        self.manifest['acceptedSamples'][path] = {'sha256':digest, 'role':'sku','skuKey':'blue',
                                                 'sourceSkuId':'901','evidence':'商家已选择当前预览'}
        file = self.parent/path
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_bytes(content)
        return file

    def query(self, *args):
        env = clean_environment(self.root/'chat')
        env.update(HEIDENG_MERCHANT_HOME=str(self.state),PYTHONIOENCODING='utf-8')
        result = subprocess.check_output([sys.executable,'-I','-B',str(ROOT/'scripts/merchant.py'),
            '--state',str(self.state),'task-context','--goal','sample','--shop-id','701',
            '--vender-id','802',*args],env=env, text=True,encoding='utf-8',timeout=25)
        return json.loads(result)['tasks']

    def test_new_chat_returns_immutable_accepted_image_with_exact_child_link(self):
        cmd = [sys.executable,'-I','-B',str(ROOT/'scripts/merchant.py'),'--state',str(self.state),'sample-context']
        found = json.loads(subprocess.check_output(cmd,env=clean_environment(self.root),encoding='utf-8'))
        self.assertEqual(found['selection'], 'matched')
        self.assertEqual(found['delivery']['skuUrl'], 'https://item.jd.com/103.html')
        self.assertEqual(Path(found['delivery']['imagePath']), self.original)
        other = json.loads(subprocess.check_output(cmd+['--shop-id','999'],env=clean_environment(self.root),encoding='utf-8'))
        self.assertEqual(other['selection'], 'not-found')
        result = self.query('--product-id','99')
        self.assertEqual(len(result),1)
        delivery = result[0]['sampleDelivery']
        self.assertEqual(Path(delivery['imagePath']), self.original)
        self.assertEqual(delivery['imageSha256'], sha256(self.original.read_bytes()).hexdigest())
        self.assertEqual((delivery['skuKey'], delivery['spec']),('blue','蓝色/L'))
        self.assertEqual(delivery['skuUrl'],'https://item.jd.com/103.html')
        self.assertEqual(delivery['productId'],'99')
        self.assertIn('status',delivery['upload'])
        self.assertIn('kind',delivery['comparison'])
        self.assertEqual(self.query('--product-id','81'),[])

    def test_unverified_sku_never_falls_back_to_source_or_spu(self):
        m = self.manifest
        for bad in [dict(self.remote,productInfo={'productId':81}),
                    dict(self.remote,skuList=[{'skuId':103,'outerId':'B'},{'skuId':104,'outerId':'B'}])]:
            atomic_json(self.parent/'.publish/readback-product.json', bad)
            self.assertIsNone(target_sku(self.parent,m,'blue')['skuUrl'])
        atomic_json(self.parent/'.publish/readback-product.json', self.remote)
        m['variants'][0]['skuId'] = 104
        self.assertIsNone(target_sku(self.parent,m,'blue')['skuUrl'])
        m['productId'] = 81
        self.assertIsNone(target_sku(self.parent,m,'blue')['productId'])
        m['productId'] = None
        atomic_json(self.parent/'state.json',{'status':'INFORMATION_PENDING'})
        pending = self.query()[0]['sampleDelivery']
        self.assertEqual(pending['targetStatus'],'unpublished')
        self.assertIsNone(pending['skuUrl'])

    def test_target_change_and_broken_comparison_do_not_lose_accepted_pixels(self):
        key = next(iter(self.manifest['acceptedSamples']))
        self.manifest['acceptedSamples'][key]['targetAtAcceptance'] = {
            'productId':'99','skuId':'108','targetStatus':'verified'}
        atomic_json(self.parent/'manifest.json', self.manifest)
        digest = self.manifest['acceptedSamples'][key]['sha256']
        meta = self.sample/'.comparison'/f'{digest}.json'
        meta.parent.mkdir()
        meta.write_text('incomplete receipt')
        card = self.query()[0]['sampleDelivery']
        self.assertEqual(card['imageSha256'],digest)
        self.assertEqual(card['targetStatus'],'needs-reconciliation')
        self.assertIsNone(card['skuUrl'])
        self.assertEqual(card['comparison']['kind'],'unknown')

    def test_conflicting_versions_or_unreadable_original_remain_unresolved(self):
        second = self.accept(b'second version')
        atomic_json(self.parent/'manifest.json',self.manifest)
        card = self.query()[0]['sampleDelivery']
        self.assertEqual(card['status'],'ambiguous')
        self.assertEqual({v['imagePath'] for v in card['versions']},{str(second),str(self.original)})
        self.original.write_bytes(b'replaced outside the original acceptance')
        card = self.query()[0]['sampleDelivery']
        self.assertEqual(card['status'],'needs-verification')
        self.assertNotIn('imagePath',card)
        self.assertEqual([v['imagePath'] for v in card['versions']],[str(second)])
