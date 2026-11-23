"""Synthetic store, accessory colours and apparel sizes. No merchant network or personal state."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from heideng_merchant import gallery_patch as gallery
from tests.gallery_fixture import apply_patch, detail
from tests.test_mature_listing import module


class GalleryTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        isolated = patch.dict(os.environ, {'HEIDENG_MERCHANT_HOME': str(self.root)})
        isolated.start()
        self.addCleanup(isolated.stop)
        self.photo = self.root / 'reviewed.png'
        Image.new('RGB', (50, 50), 'blue').save(self.photo)
        self.api = Mock(STATE_ROOT=self.root)
        self.api.upload.return_value = {'imgUrl': 'new'}
        self.api.JdoError = ValueError
        self.shop = {'venderId': 5, 'shopId': 6, 'profile': 'pop-test', 'shopName': '样例店'}
        self.live = detail()
        self.read = Mock(side_effect=lambda pid: deepcopy(self.live))
        self.api.run_jdo_large.side_effect = lambda **args: apply_patch(self.live,args['body_path'])
        media = patch('heideng_merchant.sku_image_edit.media_space', return_value=('zone', 2))
        media.start()
        self.addCleanup(media.stop)

    def publish(self, **kwargs):
        return gallery.pilot(self.api, self.read, self.shop, 41, '301', self.photo, 'shared', publish=True, **kwargs)

    def test_cli_preview_then_only_one_sku_first_slot_even_if_public_and_second_slot_share_url(self):
        entry = module('image_patch_update')
        argv = ['images', 'pilot-main-image', '--profile', 'pop-test', '--sku-id', '301', '--product-id', '41']
        with patch.object(entry, 'cli', self.api), patch.object(entry, 'apply_detail', self.read):
            self.api.verify_configured_store_identity.return_value = self.shop
            with patch.object(sys, 'argv', argv + ['--check-only']):
                self.assertEqual(entry.main(), 0)
            self.api.upload.assert_not_called()
            self.api.run_jdo_large.assert_not_called()
            with patch.object(sys, 'argv', argv + ['--confirm', 'PUBLISH_ONE_SKU_FIRST_IMAGE',
                                                  '--expected-url', 'shared', '--image', str(self.photo)]):
                self.assertEqual(entry.main(), 0)
        self.assertEqual(gallery.snapshot(self.live, 41)['groups'],
                         {'blue': ['new', 'b-detail', 'shared'], 'red': ['shared', 'r-detail'], gallery.PUBLIC_GROUP: ['shared']})
        body = json.loads(self.api.run_jdo_large.call_args.kwargs['body_path'].read_text(encoding='utf-8'))
        self.assertEqual([len(json.loads(op['value'])['value']) for op in body['patchOperationList']], [1])
        evidence = self.publish()
        self.assertTrue(evidence['reconciled'])
        self.assertEqual(evidence['consumerPageStatus'], 'unchecked')
        self.assertEqual(evidence['buyerUrl'], 'https://item.jd.com/301.html')
        self.api.upload.assert_called_once()
        self.api.run_jdo_large.assert_called_once()

    def test_shared_colour_sizes_and_ambiguous_bindings_stop_before_upload(self):
        self.live['skuList'][1]['saleAttrs'] = [{'dim': 1, 'attrValues': 'blue'}, {'dim': 2, 'attrValues': 'XL'}]
        with self.assertRaisesRegex(ValueError, '301, 302'):
            self.publish()
        self.live['skuList'][1]['saleAttrs'] = [{'dim': 2, 'attrValues': 'XL'}, {'dim': 3, 'attrValues': 'L'}]
        with self.assertRaisesRegex(ValueError, '未能唯一核验'):
            self.publish()
        self.api.upload.assert_not_called()
        self.api.run_jdo_large.assert_not_called()

    def test_second_dimension_mapping_id_and_spec_uuid_collisions_do_not_identify_a_gallery(self):
        row = self.live['skuList'][0]
        for attrs, uuid in (([{'dim': 2, 'attrValues': 'blue'}], ''),
                            ([{'dim': 1, 'attrValues': 'other', 'mappingId': 'blue'}], ''),
                            ([], 'blue')):
            with self.subTest(attrs=attrs, uuid=uuid):
                row.update(saleAttrs=attrs, uuid=uuid)
                with self.assertRaisesRegex(ValueError, '未能唯一核验'):
                    self.publish()
        self.api.upload.assert_not_called()
        self.api.run_jdo_large.assert_not_called()

    def test_original_stale_or_changed_while_uploading_never_binds(self):
        with self.assertRaisesRegex(ValueError, '制作时的首图'):
            gallery.pilot(self.api, self.read, self.shop, 41, '301', self.photo, 'stale', publish=True)
        self.api.upload.assert_not_called()
        def change(*args):
            self.live['skuList'][0]['priceInfo']['jdPrice'] = 50
            return {'imgUrl': 'new'}
        self.api.upload.side_effect = change
        with self.assertRaisesRegex(ValueError, '上传期间'):
            self.publish()
        self.api.run_jdo_large.assert_not_called()

    def test_unknown_patch_survives_restart_other_sku_and_store_are_not_admitted(self):
        self.api.run_jdo_large.side_effect = TimeoutError('no response')
        with self.assertRaises(TimeoutError):
            self.publish()
        self.assertEqual(self.publish()['status'], 'awaiting-readback')
        self.assertEqual(gallery.pilot(self.api, self.read, self.shop, 41, '302', reconcile=True)['status'],
                         'different-original-edit')
        self.assertEqual(gallery.pilot(self.api, self.read, self.shop, 41, '302')['status'], 'eligible')
        for bad in ({'profile': 'pop-other'}, {'shopId': 7}, {'shopName': '另一家'}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, '其他店铺或 Profile'):
                gallery.pilot(self.api, self.read, {**self.shop, **bad}, 41, '301', reconcile=True)
        self.live['material']['mainImages'][0]['imageInfoList'][0]['imgUrl'] = 'new'
        recovered = gallery.pilot(self.api, self.read, self.shop, 41, '301', reconcile=True)
        self.assertTrue(recovered['ok'])
        self.api.run_jdo_large.assert_called_once()

    def test_unknown_upload_is_not_sent_again(self):
        self.api.upload.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            self.publish()
        with self.assertRaisesRegex(ValueError, '原素材上传结果未知'):
            self.publish()
        self.api.upload.assert_called_once()
        self.api.run_jdo_large.assert_not_called()

    def test_legacy_map_guard_and_explicit_whole_product_preserves_tenth_slot(self):
        images = self.live['material']['mainImages'][0]['imageInfoList']
        images.extend({'orderSort': i, 'imgUrl': 'shared' if i == 10 else str(i)} for i in range(4, 11))
        mapping = {'shared': 'new'}
        with self.assertRaisesRegex(ValueError, '多个图位'):
            gallery.mapped_patch(self.api, self.read, self.shop, 41, mapping)
        self.api.run_jdo_large.assert_not_called()
        result = gallery.mapped_patch(self.api, self.read, self.shop, 41, mapping, allow_shared=True)
        self.assertEqual(result['changedSlots'], 4)
        self.assertEqual(result['preservedTailSlots'], [{'group': 'blue', 'position': 10}])
        self.assertEqual(images[-1]['imgUrl'], 'shared')

    def test_frozen_refresh_deduplicates_upload_but_changes_only_approved_positions(self):
        baseline = deepcopy(self.live)
        args = (self.api, self.read, self.shop, 41, baseline, {'shared': 'new'}, [1], 9, self.root/'bodies', str)
        result = gallery.frozen_patch(*args)
        self.assertTrue(result['ok'])
        self.assertEqual(result['changedSlots'], 3)
        self.assertEqual(self.live['material']['mainImages'][0]['imageInfoList'][2]['imgUrl'], 'shared')
        self.assertTrue(gallery.frozen_patch(*args)['reconciled'])
        self.api.run_jdo_large.assert_called_once()

    def test_refresh_old_unresolved_body_waits_and_does_not_patch_again(self):
        bodies = self.root/'bodies'
        bodies.mkdir()
        (bodies/'patch_41.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, '原刷新任务留有提交体'):
            gallery.frozen_patch(self.api, self.read, self.shop, 41, self.live, {'shared': 'new'}, [1], 9, bodies, str)
        self.api.run_jdo_large.assert_not_called()
