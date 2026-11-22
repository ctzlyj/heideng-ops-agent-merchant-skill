"""Recover status from real file fingerprints and shop/SKU-specific receipts."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from heideng_merchant.safety import atomic_json, file_sha, read_json
from heideng_merchant.sample_upload_state import sample_upload_state
from heideng_merchant.sku_image_edit import run
from tests.test_category_sku_edit import Platform


class SampleStateTests(unittest.TestCase):
    def setUp(self):
        self.state = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME':str(self.state)}))
        self.store = {'shopId':'7', 'venderId':'99', 'shopName':'fixture', 'profile':'fixture'}
        atomic_json(self.state/'linker/shops.json', {'profiles':{'fixture':self.store}})
        self.package = self.state/'work/listing/sample-package'
        self.edit_dir = self.state/'work/sku-image-edits/99/42'
        self.api = Platform(19, ['20','21'])
        self.photo = self.state/'accepted.jpg'
        Image.new('RGB',(480,480), 'green').save(self.photo)
        self.sha = file_sha(self.photo)
        atomic_json(self.package/'manifest.json', {'store':self.store,'productId':42,'status':'VERIFIED'})
        atomic_json(self.package/'state.json', {'productId':42,'status':'SUCCEEDED'})

    def state_for(self, sku='20', sha=None, shop='7'):
        return sample_upload_state(self.state, shop,'99','42',sku,sha or self.sha,package=self.package)

    def edit(self, sid='20'):
        return run(self.api, lambda _:copy.deepcopy(self.api.detail),self.store,42,{sid:self.photo})

    def test_lost_edit_and_historical_readback(self):
        self.assertEqual(self.state_for()['status'], 'no-recorded-upload')
        self.api.lose_response = True
        with self.assertRaises(TimeoutError):
            self.edit()
        self.assertEqual(self.state_for()['status'], 'edit-unknown')
        self.assertEqual(self.state_for('21')['status'], 'uploaded')
        self.assertEqual(self.state_for(shop='8')['status'], 'no-recorded-upload')
        run(self.api, lambda _:copy.deepcopy(self.api.detail),self.store,42,{},reconcile=True)
        result = self.state_for()
        self.assertEqual(result['status'], 'verified-as-of')
        self.assertTrue(result['checkedAt'])
        self.assertEqual(result['consumerPageStatus'], 'unchecked')
        self.assertEqual(self.state_for('21')['status'], 'other-image-as-of')
        self.assertEqual(self.state_for(sha='f'*64)['status'], 'no-recorded-upload')
        self.assertEqual((self.api.uploads,self.api.edits), (1,1))

    def test_upload_and_submission_stages(self):
        media = self.edit_dir/'uploads'/f'{self.sha}.json'
        row = {'sha256':self.sha, 'productId':42, 'shopIdentity':self.store}
        atomic_json(media, {**row,'status':'uploading'})
        self.assertEqual(self.state_for()['status'], 'upload-unknown')
        atomic_json(media, {**row,'status':'accepted','url':'jfs/picture'})
        self.assertEqual(self.state_for()['status'], 'uploaded')
        record = dict(productId=42,shopIdentity=self.store,inputs={'20':self.sha},expected={'20':'jfs/picture'})
        current = self.edit_dir/'current.json'
        for status, known in [('submitted','submitted'),('awaiting-readback','submitted'),('rejected','edit-rejected')]:
            atomic_json(current, dict(record,status=status))
            self.assertEqual(self.state_for()['status'],known)
        atomic_json(current, dict(record,status='verified',readback={}))
        self.assertEqual(self.state_for()['status'],'unresolved')

    def test_publication_and_conflicting_later_edit(self):
        url = self.api.detail['skuList'][0]['logo']
        atomic_json(self.package/'.publish/uploads.json', {self.sha:{'status':'SUCCEEDED','sha256':self.sha,'imgUrl':url}})
        atomic_json(self.package/'.publish/readback-product.json', self.api.detail)
        self.assertEqual(self.state_for()['status'],'verified-as-of')
        self.assertEqual(self.state_for('21')['status'],'uploaded')
        atomic_json(self.edit_dir/'current.json', {'productId':42,'shopIdentity':self.store,'inputs':{'20':'f'*64},
                    'expected':{'20':'jfs/new'},'status':'submitting'})
        self.assertEqual(self.state_for()['status'],'later-edit-pending')
        self.assertEqual(self.state_for(shop='8')['status'],'no-recorded-upload')
