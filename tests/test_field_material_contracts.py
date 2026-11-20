"""Field g9jb return-shape/credential-routing regressions; no merchant writes/keys."""
import io,json,os,tempfile,unittest
from contextlib import redirect_stdout
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock,patch
import tests.test_mature_materials as helpers

class SavedKeyRoutingTests(unittest.TestCase):
    def test_actual_image_boundary_reuses_only_explicit_merchant_state(self):
        from heideng_merchant.mature_image import merchant_key
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d},clear=True),patch('heideng_merchant.merchant_key_store.read_key',return_value='synthetic-merchant-key') as read:
            try:value=merchant_key()
            except Exception as error:self.fail(f'已记住的商家Key应被实际图片边界复用：{error}')
        self.assertEqual(value,'synthetic-merchant-key');read.assert_called_once_with(Path(d))
    def test_no_explicit_merchant_state_never_reads_default_personal_store(self):
        from heideng_merchant.mature_image import merchant_key
        with patch.dict(os.environ,{},clear=True),patch('heideng_merchant.merchant_key_store.read_key') as read:
            with self.assertRaises(Exception) as failure:merchant_key()
        read.assert_not_called();self.assertIn('with_image_key.py',str(failure.exception))

class FieldMaterialTests(unittest.TestCase):
    setUp=helpers.MatureMaterialsTests.setUp
    tearDown=helpers.MatureMaterialsTests.tearDown
    agent=helpers.MatureMaterialsTests.agent
    def test_model_client_standard_route_uses_saved_key_without_prompt(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d},clear=True),patch('heideng_merchant.merchant_key_store.read_key',return_value='synthetic-key'),patch('heideng_merchant.lts4ai_client.SfImage2Client') as provider:
            try:client=a.ModelClient('')
            except Exception as error:self.fail(f'已批准生图不能因为入口不同丢掉商家Key：{error}')
            client.close()
        self.assertEqual(provider.call_args.args[0],'synthetic-key')
    def test_estimate_merges_sibling_deficits_and_counts_approved_image_reuse(self):
        a=self.agent()
        rows=[{'productId':'11','skuId':'1','slots':{'white':{'state':'missing'},'scene1':{'state':'missing'},'transparent':{'state':'missing'}}},
              {'productId':'11','skuId':'2','slots':{'white':{'state':'approved','approvedValues':['https://img14.360buyimg.com/imgzone/white.jpg']},'scene1':{'state':'approved','approvedValues':['https://img14.360buyimg.com/imgzone/scene.jpg']},'transparent':{'state':'missing'}}}]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'audit.json';p.write_text(json.dumps({'rows':rows}),encoding='utf-8');result=a.audit_generation_summary(p)
        self.assertEqual(result['missingSlotCount'],3)
        self.assertEqual(result['imageGenerationRequestCount'],0)
        self.assertEqual(result['reuseImageSlotCount'],2);self.assertEqual(result['transparentDerivationCount'],1)
    def test_transparent_is_local_not_a_fifth_paid_image(self):
        a=self.agent()
        rows=[{'productId':'11','slots':{k:{'state':'missing'} for k in ('white','scene1','scene2','selling','transparent')}}]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'audit.json';p.write_text(json.dumps({'rows':rows}),encoding='utf-8');result=a.audit_generation_summary(p)
        self.assertEqual(result['imageGenerationRequestCount'],4)
        self.assertEqual(result['transparentDerivationCount'],1)
    def test_scoped_audit_does_not_compare_one_product_to_whole_shop(self):
        a=self.agent();identity={'shopName':'fixture','venderId':'123','shopId':'123'}
        class Client:
            def seller_info(self):return {**identity,'success':True,'whitelistMatch':True,'isPop':True,'active':True}
            def online_products(self,*_):raise AssertionError('目标核验不能取全店集合比较')
            def health_infos(self,*_):raise AssertionError('test transport replacement missing')
            def skus(self,ids):return [{'productId':'11','skuId':'1','skuName':'fixture','status':103}]
        with patch.object(a,'collect_jdo_pages_parallel',return_value=[]),patch.object(a,'_query_binding_materials',return_value={'1':[]}):
            result=a.audit_pop_coverage(Client(),'fixture',product_ids=['11'],authorized_sku_ids=['1'])
        self.assertEqual(result['onlineProductCount'],1);self.assertEqual(result['onlineSkuCount'],1)

    def test_free_repair_preserves_submissions_appeals_and_exact_remaining_without_reading_key(self):
        a=self.agent();import pop_repair
        identity={'shopName':'fixture','venderId':'123','shopId':'123'}
        def slot(reason):return {'state':'rejected','auditReasons':[reason]}
        rows=[{'skuId':'1','productId':'11','skuName':'fixture','slots':{'transparent':slot('抠图损坏'),'white':{'state':'approved'}}},
              {'skuId':'2','productId':'22','skuName':'fixture','slots':{'white':slot('禁止出现文字信息')}},
              {'skuId':'3','productId':'33','skuName':'fixture','slots':{'scene1':slot('背景不合规')}}]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'repair-scope.json').write_text(json.dumps({'shopIdentity':identity,'rows':rows,'skuSources':{'1':{},'2':{},'3':{}},
              'originals':{'1':[],'2':[{'materialType':31,'order':1,'status':5,'url':'https://img14.360buyimg.com/imgzone/printed.jpg'}],'3':[]}}),encoding='utf-8')
            args=Namespace(profile='fixture',expected_shop_name='fixture',output_dir=root,confirm='AUTO_MAINTAIN',profile_dir=str(root/'browser'),no_paid_generation=True)
            client=Mock();client.seller_info.return_value=identity
            with patch.object(a,'JdoClient',return_value=client),patch.object(pop_repair,'run_jingmai_first',return_value=({('1','transparent')},{'submittedSlots':1,'tasks':[{'status':'task-accepted'}]})),patch.object(a,'export_pop_image_appeals',return_value={'appealFiles':['fixture-appeal.xlsx'],'appealSubmitted':False}),patch.object(a,'ModelClient') as model,patch('heideng_merchant.merchant_key_store.read_key') as read,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d},clear=True):
                try:result=pop_repair.run_rejected_repairs(args,a)
                except Exception as error:self.fail(f'免费修复不能靠缺Key抛异常收尾：{error}')
            self.assertEqual(result['status'],'partial-free-repair');self.assertEqual(result['remainingImageSlotCount'],1)
            self.assertEqual(result['remainingTargets'],[{'spuId':'33','skuId':'3','kinds':['scene1']}])
            self.assertEqual(result['jingmaiFirst']['submittedSlots'],1);self.assertIsNotNone(result['productTextAppeals'])
            model.assert_not_called();read.assert_not_called()
    def test_free_repair_flag_is_explicit_and_auto_handoff_does_not_authorize_paid_repairs(self):
        a=self.agent()
        parsed=a.build_parser().parse_args(['repair-rejected','--profile','fixture','--expected-shop-name','fixture','--output-dir','fixture','--confirm','AUTO_MAINTAIN','--no-paid-generation'])
        self.assertFalse(parsed.paid_generation)

    def test_binding_progress_comes_from_accepted_receipt_and_exact_readback(self):
        a=self.agent();url='https://img14.360buyimg.com/imgzone/jfs/white.jpg'
        row=a.SourceRow('1','fixture','11');job=a.SpuJob('11','1','fixture',('1',),(('1','fixture'),),needs_selling_points=False,needs_scenes=False,needs_selling_image=False,needs_transparent=False)
        prepared=a.PreparedSource('fixture','Sheet1',(),(row,),(job,),1,1,0)
        client=Mock();client.bind_sku_materials.return_value={'success':True}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state={'jobs':{'11':{'uploaded_urls':{'white':url}}}};a._bind_state(state,prepared,root/'.state/task.json')
            with patch.object(a,'_query_binding_materials',return_value={'1':[]}):plan=a.prepare_material_binding_plan(client,prepared,root)
            actual={'1':[{**a._binding_material(31,1,url,'1'),'status':3}]}
            with patch.object(a,'_query_binding_materials',return_value=actual),redirect_stdout(io.StringIO()) as out:
                result=a.execute_material_binding_plan(client,plan)
        events=[json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([e['event'] for e in events],['binding-submitted','binding-readback'])
        self.assertEqual(events[0]['skuCount'],1);self.assertEqual(result.pending_spus,1)
        self.assertNotIn(url,out.getvalue());client.bind_sku_materials.assert_called_once()
    def test_historical_missing_source_metadata_cannot_be_quoted_as_precise_new_images(self):
        a=self.agent();rows=[{'productId':'11','slots':{'white':{'state':'missing'}}},{'productId':'11','slots':{'white':{'state':'approved'}}}]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'audit.json';p.write_text(json.dumps({'rows':rows}),encoding='utf-8');result=a.audit_generation_summary(p)
        self.assertFalse(result['estimateComplete']);self.assertIsNone(result['imageGenerationRequestCount'])

    def test_free_repair_with_remaining_work_is_not_presented_as_only_review_wait(self):
        from heideng_merchant.merchant_experience import task_summary
        result=task_summary({'status':'partial-free-repair','remainingImageSlotCount':1,'pendingReviewCount':2})
        self.assertEqual(result['phase'],'needs-agent-action');self.assertFalse(result['completed']);self.assertFalse(result['retryAllowed'])
    def test_saved_key_is_not_implicit_permission_for_paid_repair_defaults(self):
        a=self.agent()
        repair=a.build_parser().parse_args(['repair-rejected','--profile','fixture','--expected-shop-name','fixture','--output-dir','fixture','--confirm','AUTO_MAINTAIN'])
        auto=a.build_parser().parse_args(['auto-maintain','--output-dir','fixture','--confirm','AUTO_MAINTAIN'])
        self.assertFalse(getattr(repair,'paid_generation',True));self.assertFalse(getattr(auto,'paid_repairs',True))

class FreeWrapperTests(unittest.TestCase):
    def test_image_key_wrapper_does_not_prompt_or_read_key_for_free_repair(self):
        import scripts.with_image_key as wrapper
        with tempfile.TemporaryDirectory() as d,patch.object(wrapper,'main',return_value=0),patch.object(wrapper,'with_key',return_value=99) as key,patch('heideng_merchant.runtime_dependencies.ensure_core'),patch.object(wrapper,'preflight'):
            result=wrapper.entry(['--state',d,'run','materials','--','repair-rejected','--profile','fixture','--expected-shop-name','fixture','--output-dir',d,'--confirm','AUTO_MAINTAIN'])
        self.assertEqual(result,0);key.assert_not_called()

if __name__=='__main__':unittest.main()
