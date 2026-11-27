import copy
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from heideng_merchant.sample_comparison import before_for_sku, read_comparison, write_comparison
from heideng_merchant.safety import file_sha
from heideng_merchant.sample_comparison import original_image_url


from tests.test_mature_listing import module


def pixels(color):
    stream = io.BytesIO()
    Image.new('RGB',(24,24),color).save(stream,'JPEG')
    return stream.getvalue()


class ComparisonOriginTests(unittest.TestCase):
    def test_gallery_display_variant_is_retrieved_from_the_original_path(self):
        for path in ('/n0/jfs/synthetic/bag.jpg','/n12/jfs/synthetic/bag.jpg'):
            self.assertEqual(original_image_url('https://img10.360buyimg.com'+path),
                             'https://img10.360buyimg.com/imgzone/jfs/synthetic/bag.jpg')

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.sample = self.root/'sample.jpg'
        self.sample.write_bytes(pixels('red'))
        self.target = {'productId':'31','skuId':'201'}
        self.detail = {'productInfo':{'productId':'31'}, 'skuList':[
            {'skuId':202,'productId':31,'logo':'jfs/other.jpg'},
            {'skuId':201,'productId':31,'logo':'jfs/blue.jpg'}]}

    def test_target_receipt_uses_exact_variant_and_both_image_hashes(self):
        urls = []
        def fetch(url):
            urls.append(url)
            return pixels('blue')
        proof = before_for_sku(self.root,self.detail,self.target,readback_source='fixture',
                               fetch=fetch)
        self.assertEqual(urls, ['https://img10.360buyimg.com/imgzone/jfs/blue.jpg'])
        result = write_comparison(self.root,self.sample,proof)
        def query(sku='201'):
            return read_comparison(self.root,sample_sha=file_sha(self.sample),target_sku_id=sku,
                                   target_product_id='31',source_sku_id='100',source_product_id='15')
        self.assertEqual(query()['skuUrl'],'https://item.jd.com/201.html')
        self.assertEqual(query()['kind'],'target-sku')
        self.assertEqual(query('202')['status'],'unverified')
        Path(result['original']).write_bytes(pixels('green'))
        self.assertEqual(query()['status'],'unverified')

    def test_legacy_migration_requires_same_pixels_and_owned_cdn(self):
        original = self.root/'earlier.bin'
        original.write_bytes(pixels('blue'))
        matches = {file_sha(original)}
        with self.assertRaisesRegex(ValueError,'字节'):
            before_for_sku(self.root,self.detail,self.target,existing=matches,
                           readback_source='fixture',fetch=lambda url:pixels('black'))
        self.assertFalse((self.root/'.comparison').exists())
        detail = copy.deepcopy(self.detail)
        detail['skuList'][1]['logo'] = 'https://example.org/jfs/blue.jpg'
        with self.assertRaisesRegex(ValueError,'图片空间'):
            before_for_sku(self.root,detail,self.target,readback_source='fixture',fetch=lambda _:self.fail())
        proof = before_for_sku(self.root,self.detail,self.target,existing=matches,
                               readback_source='historic-product',fetch=lambda url:pixels('blue'))
        self.assertIn('/n1/jfs/blue.jpg',proof['imageUrl'])
        self.assertEqual(proof['beforeSha256'],file_sha(original))

    def test_source_and_merchant_reference_do_not_inherit_target_link(self):
        pl = module('photo_listing')
        source = self.root/'cover.jpg'
        source.write_bytes(pixels('blue'))
        entry = {'productPhoto':'cover.jpg','sourceUrl':'https://img10.360buyimg.com/imgzone/jfs/a.jpg',
                 'sha256':file_sha(source)}
        pl.atomic_json(self.root/'.reference-cache/assets.json',{'entries':[entry],'sourceSpuId':'15'})
        task = {'id':'cover','sourceSkuId':'100','firstImageReference':'cover.jpg'}
        pl.atomic_json(self.root/'plan.json',[task])
        m = {'reference':{'cacheManifest':'.reference-cache/assets.json'},'mainImages':[
            {'id':'cover','localPath':'sample.jpg'}]}
        review = pl.sample_review(self.root,m)
        self.assertIn('复刻来源',review['layout'])
        def read():
            return read_comparison(self.root,sample_sha=file_sha(self.sample),target_sku_id='201',
                                   target_product_id='31',source_sku_id='100',source_product_id='15')
        self.assertEqual(read()['skuUrl'],'https://item.jd.com/100.html')
        self.assertEqual(read_comparison(self.root,sample_sha=file_sha(self.sample))['status'],'unverified')
        task['comparisonPhoto'] = 'cover.jpg'
        pl.atomic_json(self.root/'plan.json',[task])
        pl.sample_review(self.root,m)
        self.assertEqual(read()['kind'],'merchant-provided')
        self.assertIsNone(read()['skuUrl'])
