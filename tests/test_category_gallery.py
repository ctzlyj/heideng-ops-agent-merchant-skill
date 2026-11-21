"""Merchant-facing visual evidence across category, SKU structure and gallery layouts."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from tests.test_mature_listing import module


def product(title, ids, shared=True, variants=True):
    def gallery(group, urls):
        return {'uuid':group, 'imageInfoList':[
            {'imgUrl':'jfs/'+url, 'orderSort':order} for order, url in reversed(list(enumerate(urls,1)))]}
    groups = [gallery('0000000000', ['shared'])] if shared else []
    skus, images = [], []
    for i, sku_id in enumerate(ids):
        sku = {'skuId':sku_id, 'uuid':'uid-'+sku_id, 'saleAttrs':[
            {'dim':1,'attrValues':str(i),'attrValueAlias':f'款-{i}'},
            {'dim':2,'attrValues':'9','attrValueAlias':'尺寸'}]}
        if variants:
            groups.append(gallery(str(i), [sku_id+'-front', sku_id+'-back']))
            sku['logo'] = 'jfs/'+sku_id+'-logo'
            images.append({'uuid':sku['uuid'], 'imageUrl':'jfs/'+sku_id+'-spec'})
        skus.append(sku)
    return {'data':{'productInfo':{'productId':'701','productName':title},'skuList':skus,
            'material':{'mainImages':groups,'ggtImages':images,'whiteBackGroundImages':[{'imageUrl':'jfs/not-a-gallery'}]}}}


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.pl = module('photo_listing')
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))/'package'
        self.store = {'profile':'fixture-shop','venderId':99,'shopName':'测试店'}
        self.enterContext(patch.object(self.pl, 'ensure_shop', return_value=self.store))
        self.enterContext(patch.object(self.pl, 'verify_store'))
        client = self.enterContext(patch.object(self.pl, 'HttpClient')).return_value
        buf = io.BytesIO()
        Image.new('RGB',(16,20),'navy').save(buf,'JPEG')
        client.get_bytes.return_value = buf.getvalue()

    def cli(self, command, *args, root=None, success=True):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = self.pl.main([command,'--package',str(root or self.root), *map(str,args)])
        value = json.loads(out.getvalue())
        self.assertEqual(rc, 0 if success else 2, value)
        return value

    def init(self, title, ids, **kwargs):
        with patch.object(self.pl.cli, 'get', return_value=product(title,ids,**kwargs)):
            self.cli('init','--shop','测试店','--source-spu','701','--title',title)
        m = self.pl.read_manifest(self.root)
        m['facts']['skus'] = [{'key':'new-'+sku, 'sourceSkuId':sku, 'spec':str(i)} for i,sku in enumerate(ids)]
        self.pl.atomic_json(self.root/'manifest.json',m)
        return self.pl.load(self.root/'.reference-cache/assets.json')

    def test_apparel_gallery_assigns_spec_and_color_images_by_sku_and_order(self):
        evidence = self.init('衬衣',['101','102'])
        subset = evidence['sourceSkus']['101']
        self.assertEqual(len(subset['firstImageCandidates']),4)
        self.assertEqual(subset['consumerPageStatus'],'unchecked')
        self.assertEqual([e['sourceUrl'].split('/')[-1] for e in evidence['entries']
                          if e['role']=='sku_main' and e['group']=='0'],['101-front','101-back'])
        self.assertFalse(any('not-a-gallery' in e['sourceUrl'] for e in evidence['entries']))
        bad_photo = evidence['sourceSkus']['102']['firstImageCandidates'][0]
        image = {'id':'sample','skuKey':'new-101','role':'sku','photos':[bad_photo],
                 'firstImageReference':subset['firstImageCandidates'][0], 'prompt':'宿主设计', 'identityChecks':'版型、色差'}
        file = self.root/'design.json'
        self.pl.atomic_json(file,{'styleObservations':'已查看所选规格','images':[image]})
        self.assertIn('另一规格',self.cli('make-sample','--image-id','sample','--image-prompts-file',file,success=False)['message'])

    def test_book_without_variant_gallery_uses_shared_and_does_not_assume_live_first(self):
        evidence = self.init('图书',['201'],variants=False)
        book = evidence['sourceSkus']['201']
        self.assertEqual(book['firstImageCandidates'],[evidence['entries'][0]['productPhoto']])
        self.assertEqual(book['consumerPageStatus'],'unchecked')

    def test_single_sample_has_one_quote_can_reuse_without_replacing_full_plan(self):
        evidence = self.init('工具组合',['301','302'],shared=False)
        sku = evidence['sourceSkus']['302']
        first = sku['firstImageCandidates'][1]
        shot = self.root/first
        self.cli('record-first-view','--source-sku','302','--url','https://item.jd.com/301.html',
                 '--product-photo',first,'--screenshot',shot,success=False)
        self.cli('record-first-view','--source-sku','302','--url','https://item.jd.com/302.html',
                 '--product-photo',first,'--screenshot',shot)
        file = self.root/'design.json'
        image = {'id':'target','role':'sku','skuKey':'new-302','firstImageReference':first,
                 'identityChecks':'套装的组成和数量','prompt':'宿主为本次套装设计',
                 'photos':sku['variantPhotos'][:2]}
        design = {'styleObservations':'已查看该规格组合图','images':[image,dict(image,id='extra')]}
        self.pl.atomic_json(file,design)
        self.pl.atomic_json(self.root/'plan.json',['existing-full-plan'])
        args = ('--image-id','target','--image-prompts-file',file)
        response = self.cli('make-sample',*args)
        self.assertEqual(response['quote']['units'],['target'])
        sample = Path(response['samplePackage'])
        self.assertEqual(len(self.pl.load(sample/'plan.json')[0]['photos']),2)
        # Exercise the real review and adoption without submitting a model request.
        image['reusePhoto'] = first
        self.pl.atomic_json(file,design)
        self.assertEqual(self.cli('make-sample',*args)['quote']['units'],[])
        self.cli('generate',root=sample)
        proof = self.cli('review',root=sample)['sampleReview']
        self.assertEqual(proof['consumerPageStatus'],'host-observed')
        self.assertTrue(Path(proof['comparison']).is_file())
        accepted = self.cli('accept-sample','--image-id','target','--evidence','商家答复 #2')
        self.assertTrue((self.root/accepted['reusePhoto']).is_file())
        self.assertEqual(json.loads((self.root/'plan.json').read_bytes()),['existing-full-plan'])
