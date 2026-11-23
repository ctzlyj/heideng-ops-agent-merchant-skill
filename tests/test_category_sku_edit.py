import copy
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from heideng_merchant import sku_image_edit as edit


class Platform:
    def __init__(self, category, ids):
        self.ids = ids
        self.detail = {'productInfo':{'productId':42,'productName':'fixture', 'productStatus':103,
                                     'categoryDetail':{'lastCategoryId':category}},
                       'material':{'mainImages':[]},
                       'skuList':[{'skuId':int(s),'productId':42,'outerId':'item-'+s,'logo':'jfs/old-'+s,
                                   'priceInfo':{'jdPrice':15},'stockNum':2} for s in ids]}
        self.schema = [{'componentCode':'WareTitle','value':'fixture'},
                       {'componentCode':'SKUS','value':[
                           {'componentCode':'SKU','value':[{'componentCode':'SkuId','value':int(s)},
                            {'componentCode':'SkuVendorSku','value':'item-'+s},
                            {'componentCode':'SkuJdprice','value':'15'},
                            {'componentCode':'SkuStockNum','value':2},
                            {'componentCode':'FutureAttr','value':{'data':[1,'keep']}}]} for s in reversed(ids)]}]
        self.uploads = 0
        self.edits = 0
        self.swap = False
        self.lose_response = False

    def get(self, _skill, url, _params=None):
        if url.endswith('/product-schemas'):
            return {'data':[json.dumps(self.schema)]}
        if url.endswith('/media-zones'):
            return {'data':[{'zoneType':1, 'zoneId':'z'}]}
        if url.endswith('/categories'):
            return {'data':[{'categoryId':12,'status':1}]}
        if url.endswith('/products/{productId}'):
            return {'data':copy.deepcopy(self.detail)}
        raise AssertionError(url)

    def upload(self, zone, category, path):
        self.uploads += 1
        return {'imgUrl':'jfs/'+edit.file_sha(path)}

    def command_edit_product(self, args):
        self.edits += 1
        body = json.loads(args.body.read_bytes())
        assert body['productApplyDTO']['saveActionType'] == 0
        skus = edit.components(json.loads(body['schema']))['SKUS']['value']
        result = {}
        for sku in skus:
            items = edit.components(sku['value'])
            assert 'SkuStockNum' not in items and items['FutureAttr']['value']['data'] == [1,'keep']
            sid = str(items['SkuId']['value'])
            if 'SkuGgtImage' in items:
                props = {item['key']:item['value'] for item in items['SkuGgtImage']['value'][0]['properties']}
                assert props['imgRefId'] == sid
                result[sid] = props['imgUrl']
        if self.swap:
            result = dict(zip(result, reversed(list(result.values()))))
        for row in self.detail['skuList']:
            key = str(row['skuId'])
            row['logo'] = result.get(key, row['logo'])
        if self.lose_response:
            raise TimeoutError('simulated response loss')


class ProductImageExclusionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME':str(self.root)}))
        self.photo = self.root/'lamp.png'
        Image.new('RGB',(480,480),'green').save(self.photo)
        self.shop = {'profile':'fixture','shopName':'灯具店','venderId':99}
        self.api = self.product(42)

    def product(self, pid):
        from tests.gallery_fixture import apply_patch
        api = Platform(7, ['81'])
        api.STATE_ROOT = self.root/'mature'/'listing'
        api.detail['productInfo']['productId'] = pid
        api.detail['skuList'][0]['productId'] = pid
        api.detail['material']['mainImages'] = [{'uuid':'81','imageInfoList':[{'orderSort':1,'imgUrl':'original'}]}]
        props = [{'key':'orderSort','value':'1'},{'key':'colorId','value':'81'},{'key':'imgUrl','value':'original'}]
        api.schema.append({'componentCode':'WareSkuImg','value':[{'componentCode':'img','properties':props}]})
        def publish(**kwargs):
            result = apply_patch(api.detail,kwargs['body_path'])
            props[-1]['value'] = api.detail['material']['mainImages'][0]['imageInfoList'][0]['imgUrl']
            return result
        api.run_jdo_large = publish
        return api

    def spec(self, **options):
        return edit.run(self.api, lambda pid:copy.deepcopy(self.api.detail), self.shop,42,{'81':self.photo},**options)

    def main_image(self, api=None, pid=42, read=None, **options):
        from heideng_merchant.gallery_patch import pilot
        api = api or self.api
        reader = read or (lambda requested:copy.deepcopy(api.detail))
        return pilot(api,reader,self.shop,pid,'81',self.photo,'original',**options)

    def test_pending_full_schema_blocks_gallery_publish_but_each_original_can_reconcile(self):
        self.api.lose_response = True
        with self.assertRaises(TimeoutError):
            self.spec()
        with self.assertRaisesRegex(ValueError,'规格图整版编辑'):
            self.main_image(publish=True)
        self.assertEqual(self.main_image()['writes'],0)
        self.assertEqual((self.api.edits,self.api.uploads),(1,1))
        self.assertEqual(self.spec(reconcile=True)['status'],'verified')
        self.assertTrue(self.main_image(publish=True)['ok'])

    def test_pending_gallery_blocks_full_schema_with_no_second_upload(self):
        def lost_response(**kwargs):
            raise TimeoutError('synthetic patch receipt loss')
        self.api.run_jdo_large = lost_response
        with self.assertRaises(TimeoutError):
            self.main_image(publish=True)
        with self.assertRaisesRegex(ValueError,'主图提交'):
            self.spec()
        self.assertEqual((self.api.edits,self.api.uploads),(0,1))
        self.assertEqual(self.spec(check_only=True)['writes'],0)
        # A document from an older worker contains just the pending status. It still
        # blocks a new write, but it may never obstruct reading back the first patch.
        edit.atomic_json(edit.sku_edit_directory(self.shop,42)/'current.json',{'status':'submitted'})
        self.assertEqual(self.main_image(reconcile=True)['status'],'awaiting-readback')
        self.api.detail['material']['mainImages'][0]['imageInfoList'][0]['imgUrl'] = 'jfs/'+edit.file_sha(self.photo)
        self.assertEqual(self.main_image(reconcile=True)['status'],'verified-in-edit-detail')

    def test_same_product_waits_and_another_product_can_publish_while_edit_is_in_flight(self):
        at_edit, release, started_gallery, entered_gallery = (threading.Event() for _ in range(4))
        original = self.api.command_edit_product
        def pause(args):
            at_edit.set()
            if not release.wait(8):
                raise TimeoutError('test did not release full schema edit')
            original(args)
        def read_after_lock(_pid):
            entered_gallery.set()
            return copy.deepcopy(self.api.detail)
        def publish_main():
            started_gallery.set()
            return self.main_image(read=read_after_lock,publish=True)
        self.api.command_edit_product = pause
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending_edit = pool.submit(self.spec)
            try:
                self.assertTrue(at_edit.wait(3))
                pending_gallery = pool.submit(publish_main)
                self.assertTrue(started_gallery.wait(3))
                self.assertTrue(self.main_image(self.product(43),pid=43,publish=True)['ok'])
                self.assertFalse(entered_gallery.wait(0.1))
            finally:
                release.set()
            self.assertEqual(pending_edit.result(timeout=4)['status'],'verified')
            self.assertTrue(pending_gallery.result(timeout=4)['ok'])
            self.assertTrue(entered_gallery.is_set())
        self.assertEqual((self.api.edits,self.api.uploads),(1,2))


class SkuImageEditTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for color in ('red','green'):
            Image.new('RGB', (480,480), color).save(self.root/(color+'.jpg'))
        environment = patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME':str(self.root/'state')})
        environment.start()
        self.addCleanup(environment.stop)
        self.identity = {'profile':'fixture','shopName':'fixture','venderId':'99'}

    def invoke(self, platform, mapping, **kwargs):
        return edit.run(platform, lambda _pid:copy.deepcopy(platform.detail), self.identity, 42,
                        {k:self.root/(v+'.jpg') for k,v in mapping.items()}, **kwargs)

    def test_single_book_and_multi_size_apparel(self):
        for vendor, category, ids in [('12',1,['11']),('13',2,['11','12','13'])]:
            self.identity['venderId'] = vendor
            api = Platform(category, ids)
            self.assertEqual(self.invoke(api, {}, check_only=True)['status'], 'eligible')
            changes = {'11':'red','12':'red'} if len(ids)>1 else {'11':'red'}
            result = self.invoke(api, changes)
            self.assertEqual(result['status'], 'verified')
            self.assertTrue(all(result['skuMatches'].values()))
            self.assertEqual(api.uploads, 1)
            if len(ids)>1:
                self.assertEqual(api.detail['skuList'][-1]['logo'], 'jfs/old-13')
            self.assertEqual(self.invoke(api, changes)['status'], 'verified')
            self.assertEqual(api.edits, 1)

    def test_swapped_skus_and_unknown_never_resubmitted(self):
        api = Platform(45, ['21','22'])
        api.swap = True
        changes = {'21':'green','22':'red'}
        first = self.invoke(api, changes)
        self.assertEqual(first['status'], 'awaiting-readback')
        self.assertEqual(first['skuMatches'], {'21':False,'22':False})
        self.assertEqual(self.invoke(api, changes)['status'], 'awaiting-readback')
        self.assertEqual(api.edits, 1)
        different = self.invoke(api, {'21':'green'})
        self.assertEqual(different['status'], 'prior-edit-pending')
        self.assertFalse(different['newRequestApplied'])
        self.identity['venderId'] = '100'
        api.swap, api.lose_response = False, True
        with self.assertRaises(TimeoutError):
            self.invoke(api, changes)
        recovered = self.invoke(api, {'22':'green'})
        self.assertEqual(recovered['status'], 'original-edit-recovered')
        self.assertFalse(recovered['newRequestApplied'])
        self.assertEqual(self.invoke(api, {}, reconcile=True)['status'], 'verified')
        self.assertEqual(api.edits, 2)

    def test_drift_and_missing_or_ambiguous_template_block(self):
        api = Platform(87, ['31','32'])
        api.schema[1]['value'][0]['value'][0]['value'] = 31
        with self.assertRaises(ValueError):
            self.invoke(api, {}, check_only=True)
        self.assertEqual((api.uploads,api.edits), (0,0))
        api = Platform(87, ['31'])
        real_upload = api.upload
        def with_drift(*args):
            api.detail['skuList'][0]['priceInfo']['jdPrice'] = 23
            return real_upload(*args)
        api.upload = with_drift
        with self.assertRaisesRegex(ValueError, '发生变化'):
            self.invoke(api, {'31':'green'})
        self.assertEqual(api.edits, 0)

    def test_wrong_price_missing_attributes_and_missing_gallery_stop_before_upload(self):
        for kind in ('price', 'brand', 'sale', 'category', 'gallery'):
            with self.subTest(kind=kind):
                api = Platform(87, ['31'])
                row = api.detail['skuList'][0]
                if kind == 'price':
                    row['priceInfo']['jdPrice'] = 19
                elif kind == 'brand':
                    api.detail['productInfo']['brandInfo'] = {'brandId':123}
                elif kind == 'sale':
                    row['saleAttrs'] = [{'attrId':'18','attrValueAlias':'蓝色','attrValues':'993'}]
                elif kind == 'category':
                    api.detail['productInfo']['goodsAttrInfos'] = [{'attrId':17,'values':[{'attrValue':5}]}]
                else:
                    api.detail['material']['mainImages'] = [{'uuid':'shared','imageInfoList':[
                        {'imgUrl':'jfs/one','orderSort':1}]}]
                with self.assertRaises(ValueError):
                    self.invoke(api, {'31':'green'})
                self.assertEqual((api.uploads,api.edits), (0,0))

    def test_explicit_spec_slot_is_keyed_by_uuid_not_gallery_position(self):
        api = Platform(18, ['41','42'])
        detail = api.detail
        for row in detail['skuList']:
            row['uuid'] = 'variant-'+str(row['skuId'])
            row['logo'] = 'jfs/shared-default'
        detail['material']['ggtImages'] = [
            {'uuid':'variant-42','imageUrl':'jfs/blue'}, {'uuid':'variant-41','imageUrl':'jfs/red'}]
        self.assertEqual(edit.pictures(detail,42), {'41':'jfs/red','42':'jfs/blue'})
        detail['material']['ggtImages'][0]['uuid'] = 'unrelated-variant'
        with self.assertRaisesRegex(ValueError, '归属'):
            edit.pictures(detail,42)

    def test_explicit_rejection_is_not_replayed(self):
        api = Platform(18, ['41'])
        api.JdoError = type('PlatformRefusal', (Exception,), {})
        with patch.object(api, 'command_edit_product', side_effect=api.JdoError('1010300506 fixture refusal')) as submit:
            with self.assertRaises(api.JdoError):
                self.invoke(api, {'41':'red'})
            original = self.invoke(api, {'41':'red'})
            self.assertEqual(original['status'], 'rejected')
            self.assertFalse(original['replayed'])
            submit.assert_called_once()
