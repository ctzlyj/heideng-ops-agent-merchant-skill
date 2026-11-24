"""Browser writes require the current official shop, not a matching seller number or array entry."""
from collections import defaultdict
from contextlib import nullcontext
from pathlib import Path
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests import test_mature_materials as fixtures


class MaterialPageIdentityTests(unittest.TestCase):
    def setUp(self):
        fixtures.MatureMaterialsTests.setUp(self)
        self.addCleanup(fixtures.MatureMaterialsTests.tearDown,self)
        import pop_browser
        self.b = pop_browser
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':str(self.home)}))
        self.url = 'https://api.m.jd.com/api?functionId=gmall.vender.data.get'
        self.shop = {'shopName':'样例灯具店','shopId':'101','venderId':'901'}
        self.page = Mock(url=self.b.WARE_LIST_URL)
        self.events = defaultdict(list)
        self.page.on.side_effect = lambda event,handler:self.events[event].append(handler)

    def emit(self, event, item):
        for handler in self.events[event]:
            handler(item)

    def deliver(self, data, *, url=None, other_frame=False, navigate=False):
        url = url or self.url
        request = SimpleNamespace(url=url,frame=Mock() if other_frame else self.page.main_frame,resource_type='xhr',post_data=None)
        response = SimpleNamespace(request=request,url=url,status=200,json=Mock(return_value=data))
        self.emit('request',request)
        if navigate:
            self.emit('framenavigated',self.page.main_frame)
        self.emit('response',response)
        return response

    def test_same_identity_object_wrong_type_collision_and_arrays(self):
        observed = self.b._observe_identity(self.page,self.shop['shopName'],self.shop['shopId'])
        for data in ({'data':{**self.shop,'shopId':'202','venderId':'101'}},
                     {'data':{'shopName':self.shop['shopName'],'venderId':'101'}},
                     {'data':{'shopId':'101','shopName':'另一家店'}},
                     {'data':{'shopBaseInfo':{'shopId':'101'},'shopName':self.shop['shopName']}},
                     {'data':[self.shop]}, {'data':{'shops':[self.shop]}}, {'data':{'product':self.shop}}):
            with self.subTest(data=data):
                self.emit('framenavigated',self.page.main_frame)
                self.deliver(data)
                self.assertFalse(self.b._has_shop_identity(self.page,observed))
        self.emit('framenavigated',self.page.main_frame)
        self.deliver({'code':200,'data':{'shopBaseInfo':self.shop}})
        self.assertTrue(self.b._has_shop_identity(self.page,observed))
        self.deliver({'data':{**self.shop,'shopId':'202'}})
        self.assertFalse(self.b._has_shop_identity(self.page,observed))

    def test_foreign_old_document_and_unrelated_responses_are_not_read(self):
        evidence = self.b._observe_identity(self.page,self.shop['shopName'],self.shop['shopId'])
        for controls in ({'url':'https://foreign.invalid/?functionId=gmall.vender.data.get'},
                         {'url':'https://api.m.jd.com/api?method=product.list&description=gmall.vender.data.get'},
                         {'other_frame':True},{'navigate':True}):
            with self.subTest(controls=controls):
                response = self.deliver({'data':self.shop},**controls)
                response.json.assert_not_called()
                self.assertFalse(self.b._has_shop_identity(self.page,evidence))
        current = 'https://sff.jd.com/api?method=LoginFacadeService'
        self.deliver({'data':{'shops':[self.shop]}},url=current)
        self.assertFalse(self.b._has_shop_identity(self.page,evidence))
        self.deliver({'data':{'currentShop':self.shop}},url=current)
        self.assertTrue(self.b._has_shop_identity(self.page,evidence))
        self.emit('framenavigated',self.page.main_frame)
        self.assertFalse(self.b._has_shop_identity(self.page,evidence))

    def test_wrong_shop_blocks_real_title_drawer_and_both_cutout_starts(self):
        def go(url,**kwargs):
            self.page.url = url
            self.emit('framenavigated',self.page.main_frame)
            self.deliver({'data':{'shopName':'样例灯具店','venderId':'101','shopId':'202'}})
        self.page.goto.side_effect = go
        context=Mock(pages=[self.page])
        self.enterContext(patch.object(self.b,'_open',return_value=context))
        self.enterContext(patch.object(self.b,'_playwright',return_value=lambda:nullcontext(Mock())))
        receipt = self.home/'receipt.json'
        profile = str(self.home/'profile')
        options = {'receipt_path':receipt,'expected_shop_name':self.shop['shopName'],
                   'expected_shop_id':self.shop['shopId'],'wait_ms':0}
        args = (Mock(),profile,self.home/'titles.xlsx',b'synthetic',receipt,{}, {'rowCount':1,'sha256':'0'*64},
                0,False,self.shop['shopName'],self.shop['shopId'],0)
        for action in (lambda:self.b._visit_title_batch(*args),lambda:self.b.submit_batch_cutout(profile,**options),
                       lambda:self.b.submit_jingmai_repair_batch(profile,{'11':['22']},'white-main',**options)):
            self.events.clear()
            with self.assertRaisesRegex(RuntimeError,'identity'):
                action()
            self.page.locator.assert_not_called()
            self.page.expect_response.assert_not_called()
            self.page.evaluate.assert_not_called()
            self.assertFalse(receipt.exists())
