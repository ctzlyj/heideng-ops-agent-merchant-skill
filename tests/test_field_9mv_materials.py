"""9mv field boundary regressions; synthetic data, no merchant writes or Key lookup."""
import unittest,tempfile,json,io,os,hashlib
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock,patch
from contextlib import redirect_stdout
import tests.test_mature_materials as helpers

class SellingPointsTests(unittest.TestCase):
    setUp=helpers.MatureMaterialsTests.setUp
    tearDown=helpers.MatureMaterialsTests.tearDown
    agent=helpers.MatureMaterialsTests.agent
    def test_platform_approved_points_are_reused_without_local_commercial_rewrite(self):
        a=self.agent();points=['坐浴盆榜第2名','全网低价','类目潜力爆款']
        rows=[{'productId':'11','skuId':'1'},{'productId':'11','skuId':'2'}]
        actual={'1':[{'materialType':1002,'order':i,'status':4,'textMaterial':{'contents':[p]}} for i,p in enumerate(points,1)],'2':[]}
        with patch.object(a,'_query_binding_materials',return_value=actual):missing,existing=a.inspect_unscored_materials(Mock(),rows)
        job=a.SpuJob('11','1','fixture',('1','2'),(('1','fixture'),('2','fixture')),needs_white=False,needs_scenes=False,needs_selling_image=False,needs_transparent=False)
        try:requests=a.build_material_binding_requests(job,existing['11'])
        except ValueError as error:self.fail(f'平台已通过的商家原值不应被本地词表连坐：{error}')
        self.assertEqual([m['textMaterial']['contents'][0] for m in requests[0]['body']['skuMaterials'][0]['materials']],points)
    def test_untrusted_new_points_keep_strict_validation(self):
        a=self.agent();job=a.SpuJob('11','1','fixture',('1',),(('1','fixture'),),needs_white=False,needs_scenes=False,needs_selling_image=False,needs_transparent=False)
        with self.assertRaises(ValueError):a.build_material_binding_requests(job,{'selling_points':['全网低价','爆款','坐浴盆']})
    def test_invalid_text_does_not_prevent_existing_image_binding_plan(self):
        a=self.agent();row=a.SourceRow('1','fixture','11');job=a.SpuJob('11','1','fixture',('1',),(('1','fixture'),),needs_scenes=False,needs_selling_image=False,needs_transparent=False)
        prepared=a.PreparedSource('fixture','Sheet1',(),(row,),(job,),1,1,0)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state={'jobs':{'11':{'selling_points':['全网低价','爆款','坐浴盆'],'uploaded_urls':{'white':'https://img14.360buyimg.com/imgzone/jfs/white.jpg'}}}};a._bind_state(state,prepared,root/'.state/task.json')
            with patch.object(a,'_query_binding_materials',return_value={'1':[]}):plan=a.prepare_material_binding_plan(Mock(),prepared,root)
        self.assertEqual([r['materialType'] for r in plan.requests],[31]);self.assertEqual(plan.preflight_failures[0]['materialType'],1002)

    def test_approved_points_survive_original_generation_manifest_and_template(self):
        a=self.agent();points=['坐浴盆榜第2名','全网低价','类目潜力爆款']
        job=a.SpuJob('11','1','fixture',('1',),(('1','fixture'),),needs_white=False,needs_scenes=False,needs_selling_image=False,needs_transparent=False)
        prepared=a.PreparedSource('fixture','Sheet1',(),(a.SourceRow('1','fixture','11'),),(job,),1,1,0)
        seed={'11':{'selling_points':points,'selling_points_origin':{'source':'platform-approved','spuId':'11','values':points}}}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with patch.object(a,'ModelClient',side_effect=AssertionError('不应调用文本或图片模型')):
                result=a.generate_batch(prepared,root/'reference',root,existing_materials=seed)
            self.assertEqual(result.failed_spus,0)
            with patch.object(a,'load_url_exports',return_value={}):path=a.fill_material_template(result.manifest_path,[],root/'filled.xlsx')
            from openpyxl import load_workbook
            book=load_workbook(path);self.assertEqual([book['通用场景'].cell(2,c).value for c in (3,4,5)],points);book.close()

class RepairScopeTests(unittest.TestCase):
    setUp=helpers.MatureMaterialsTests.setUp
    tearDown=helpers.MatureMaterialsTests.tearDown
    agent=helpers.MatureMaterialsTests.agent
    def test_shared_reference_and_durable_request_budget(self):
        self.agent()
        import pop_repair
        from tempfile import TemporaryDirectory
        rows=[{'skuId':'1','productId':'10'},{'skuId':'2','productId':'10'}]
        sources={'1':{'logo':'a'},'2':{'logo':'b'}}
        self.assertEqual(pop_repair.repair_references(rows,sources,{}),{'1':('1','a'),'2':('1','a')})
        self.assertEqual(pop_repair.repair_references(rows,sources,{},'sku')['2'],('2','sku:2|b'))
        with TemporaryDirectory() as directory:
            reserve,_=pop_repair.repair_request_budget(Path(directory),2,ValueError)
            reserve()
            resume,budget=pop_repair.repair_request_budget(Path(directory),None,ValueError)
            resume()
            self.assertEqual(budget,{'limit':2,'reserved':2})
            with self.assertRaisesRegex(ValueError,'budget-exhausted'):resume()
    def test_explicit_repair_kind_never_includes_other_rejected_or_missing_slots(self):
        a=self.agent();import pop_repair
        rows=[{'skuId':'1','productId':'11','slots':{'white':{'state':'rejected'},'scene1':{'state':'rejected'},'selling':{'state':'missing'}}}]
        try:result=pop_repair.scoped_repair_rows(rows,None,[],a,repair_kinds=['white'])
        except TypeError as error:self.fail(f'付费类型范围必须有明确过滤入口：{error}')
        self.assertEqual(result[0]['repairKinds'],['white'])
    def test_scope_can_only_narrow_original_known_scope(self):
        self.agent();import pop_repair
        original={'authorizedSkuIds':None,'excludedBindings':[]}
        current={'authorizedSkuIds':['1'],'excludedBindings':[],'repairKinds':['white']}
        rows=[{'skuId':'1','productId':'11'},{'skuId':'2','productId':'22'}]
        self.assertTrue(hasattr(pop_repair,'check_repair_scope_subset'),'原范围需要安全子集校验')
        pop_repair.check_repair_scope_subset(original,current,rows)
        with self.assertRaises(ValueError):pop_repair.check_repair_scope_subset(current,original,rows)
    def test_paid_repair_has_explicit_type_argument(self):
        a=self.agent()
        with redirect_stdout(io.StringIO()),redirect_stdout(io.StringIO()):
            try:args=a.build_parser().parse_args(['repair-rejected','--profile','fixture','--expected-shop-name','fixture','--output-dir','fixture','--confirm','AUTO_MAINTAIN','--paid-generation','--repair-kind','white'])
            except SystemExit:self.fail('原修复入口缺类型过滤参数')
        self.assertEqual(args.repair_kind,['white'])

    def test_default_audit_summary_is_bounded_and_reports_full_snapshot_location(self):
        a=self.agent();payload={'onlineSkuCount':20000,'materialDeficitSkuIds':[str(i) for i in range(20000)],'rejectedSkuIds':[str(i) for i in range(10000)],'rows':[],'issueCounts':{'hasShortTitle':10000}}
        self.assertTrue(hasattr(a,'audit_cli_summary'),'回查stdout应有单一简洁契约')
        result=a.audit_cli_summary(payload,{'imageGenerationRequestCount':None,'estimateComplete':False},'/original/audit.json',{})
        self.assertLess(len(json.dumps(result)),2500);self.assertEqual(result['rejectedSkuIdsCount'],10000)
        self.assertEqual(result['resultFile'],'/original/audit.json');self.assertNotIn('materialDeficitSkuIds',result)
    def test_actual_model_attempts_include_failed_response_not_only_valid_images(self):
        a=self.agent()
        from heideng_merchant.mature_image import MerchantImageClient
        with patch.object(MerchantImageClient,'edit',side_effect=RuntimeError('synthetic upstream failure')):
            client=a.ModelClient('synthetic-only')
            try:
                with self.assertRaises(RuntimeError):client.edit_image('fixture',Path('fixture.png'),model='pool')
                stats=client.image_model_stats()
            finally:client.close()
        self.assertEqual(stats.get('attempts',{}).get(a.MODELS[0]),1);self.assertEqual(stats['failures'][a.MODELS[0]],1)

    def test_approved_material_slots_share_two_models_without_duplicate_dispatch(self):
        import io
        from threading import Barrier
        from PIL import Image
        from tests.fee_consent import signed_fixture
        from heideng_merchant.mature_image import MerchantImageClient
        a = self.agent()
        job = a.SpuJob('11','1','fixture',('1',),(('1','fixture'),), needs_selling_points=False,
                       needs_white=False, needs_selling_image=False, needs_transparent=False)
        prepared = a.PreparedSource('fixture','Sheet1',(),(a.SourceRow('1','fixture','11'),),(job,),1,1,0)
        image = io.BytesIO()
        Image.new('RGB',(800,800),'blue').save(image,'JPEG')
        for legacy in (False, True):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                    'HEIDENG_MERCHANT_HOME': tmp, 'HEIDENG_MERCHANT_LTS4AI_API_KEY':'fixture'}):
                root = Path(tmp)
                (root/'refs').mkdir()
                (root/'refs/11.jpg').write_bytes(image.getvalue())
                out = root/'batch'
                def fee(approval=None):
                    return a.material_image_approval(prepared, [(prepared,out)], out, {}, {'shopId':'123'}, approval)
                offer = fee()['feeQuote']
                self.assertEqual(offer['creditCostsByUnit'],{'11/scene1':3, '11/scene2':3})
                self.assertEqual((offer['estimatedCredits'],offer['maxCredits']), (6,6))
                self.assertEqual(offer['scope']['models'],list(a.MODELS))
                if legacy:
                    del offer['scope']['models']
                    del offer['scope']['imageSize']
                    a._save_state(out/'.state/image-fee-quote.json',offer)
                approval = out/'approved.json'
                a._save_state(approval, signed_fixture(dict(offer,billing='requests',maxRequests=2)))
                both = Barrier(2)
                dispatched = []
                def edit(client, *, prompt, images, **kwargs):
                    dispatched.append(client.client.model)
                    both.wait(timeout=6)
                    return image.getvalue()
                with patch.object(MerchantImageClient,'edit',edit):
                    result = a.generate_batch(prepared,root/'refs',out,fee_context=fee(approval))
                self.assertEqual(result.failed_spus, 0)
                receipts = [json.loads(p.read_bytes()) for p in (out/'.state/image-requests').glob('*.json')]
                expected = ['gpt-image-2.5']*2 if legacy else list(a.MODELS)
                self.assertCountEqual(dispatched, expected)
                self.assertCountEqual([r['model'] for r in receipts], expected)
                self.assertEqual({r['status'] for r in receipts},{'received'})
                self.assertEqual(fee(), (out,None,None))

    def test_repair_receipts_bind_real_model_per_fresh_image_and_reuse_original_bytes(self):
        import pop_repair
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from heideng_merchant.mature_image import MerchantImageClient
        a = self.agent()
        both = Barrier(2)
        dispatched = {}
        def edit(client, *, prompt, images, size):
            self.assertEqual(size, a.MATERIAL_IMAGE_SIZE)
            dispatched[prompt] = client.client.model
            both.wait(timeout=6)
            return b'fixture'
        with tempfile.TemporaryDirectory() as tmp, patch.object(MerchantImageClient,'edit',edit):
            model = a.ModelClient('synthetic')
            self.addCleanup(model.close)
            model.max_model_requests = 2
            def run(kind):
                return pop_repair.request_repair_image(a,model,kind,kind,Path(tmp)/'ref.jpg',None,Path(tmp)/(kind+'.png'),5)
            with ThreadPoolExecutor(2) as pool:
                self.assertEqual(list(pool.map(run,['scene1','selling'])), [b'fixture']*2)
            self.assertCountEqual(dispatched.values(),a.MODELS)
            for kind, selected in dispatched.items():
                self.assertEqual(run(kind), b'fixture')
                item = json.loads((Path(tmp)/(kind+'.request.json')).read_bytes())
                self.assertEqual((item['model'],item['status']), (selected,'received'))
            self.assertEqual(sum(model.image_model_stats()['attempts'].values()), 2)

    def test_appeal_action_is_not_misreported_as_login_or_new_fee_decision(self):
        from heideng_merchant.merchant_experience import task_summary
        result=task_summary({'status':'partial-free-repair','remainingImageSlotCount':2,'manualAppealRequired':True,'needsMerchantAction':True})
        self.assertIn('申诉',result['message']);self.assertNotIn('登录',result['message']);self.assertTrue(result['needsAgentAction'])

    def test_narrowed_resume_reads_original_shared_receipt_but_returns_only_active_sku(self):
        a=self.agent();import pop_repair
        identity={'shopName':'fixture','venderId':'123','shopId':'123'};ref='https://img14.360buyimg.com/imgzone/jfs/ref.jpg';url='https://img14.360buyimg.com/imgzone/jfs/new.jpg'
        rows=[{'skuId':sku,'productId':'11','skuName':'fixture','slots':{'white':{'state':'rejected','auditReasons':['模糊']}}} for sku in ('1','2')]
        job=a.SpuJob('11','1','fixture',('1','2'),(('1','fixture'),('2','fixture')),needs_selling_points=False,needs_scenes=False,needs_selling_image=False,needs_transparent=False)
        request=a.build_material_binding_requests(job,{'uploaded_urls':{'white':url}})[0]
        material=lambda sku:{**a._binding_material(31,1,url,sku),'status':3}
        client=Mock();client.seller_info.return_value=identity;client.resolve_category.return_value=1
        client.sku_materials.return_value=[{'skuId':sku,'materials':[material(sku)]} for sku in ('1','2')]
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_LTS4AI_API_KEY':'synthetic','HEIDENG_MERCHANT_HOME':d},clear=True):
            root=Path(d);(root/'repair-scope.json').write_text(json.dumps({'shopIdentity':identity,'rows':rows,'skuSources':{sku:{'logo':ref} for sku in ('1','2')},'originals':{'1':[],'2':[]}}))
            group=hashlib.sha256(json.dumps(['11','white',ref],ensure_ascii=False).encode()).hexdigest()[:20]
            path=root/'shared-bindings'/(group+'.json');path.parent.mkdir();path.write_text(json.dumps({'status':'submitted','request':request}))
            args=Namespace(output_dir=root,profile='fixture',expected_shop_name='fixture',confirm='AUTO_MAINTAIN',authorized_sku_ids=['1'],repair_kind=['white'],paid_generation=True,jingmai_first=False,jingmai_ledger=root/'ledger.json')
            model=Mock();model.image_model_stats.return_value={'usage':{},'attempts':{}}
            with patch.object(a,'JdoClient',return_value=client),patch.object(a,'ModelClient',return_value=model),patch('heideng_merchant.mature_runtime.registered_browser_profile',return_value=None):
                from tests.test_audit_handoff_contracts import run_approved_repair
                result=run_approved_repair(args,a)
            self.assertEqual([r['skuId'] for r in result['rows']],['1'])
            self.assertEqual(json.loads(path.read_text())['request']['skuIds'],['1','2'])
            client.bind_sku_materials.assert_not_called()

    def test_request_limit_stops_quality_retry_or_parallel_work_before_extra_paid_call(self):
        a=self.agent()
        from heideng_merchant.mature_image import MerchantImageClient
        with patch.object(MerchantImageClient,'edit',return_value=b'fixture') as edit:
            model=a.ModelClient('synthetic');model.max_model_requests=1
            try:
                model.edit_image('fixture',Path('fixture.jpg'),model='pool')
                with self.assertRaisesRegex(RuntimeError,'budget'):model.edit_image('fixture',Path('fixture.jpg'),model='pool')
            finally:model.close()
        self.assertEqual(edit.call_count,1)

    def test_paid_request_cap_cannot_fall_through_to_a_second_provider(self):
        a=self.agent();import pop_repair
        from heideng_merchant.mature_image import MerchantImageClient
        with tempfile.TemporaryDirectory() as d,patch.object(MerchantImageClient,'edit',side_effect=RuntimeError('synthetic unknown output')) as edit,patch('subprocess.run') as run:
            model=a.ModelClient('synthetic');model.max_model_requests=0
            try:
                with self.assertRaisesRegex(RuntimeError,'budget'):
                    pop_repair.request_repair_image(a,model,'white','unchanged prompt',Path(d)/'ref.jpg',['JoyAgent-image(JoyAgent)','{reference}','{output}','{prompt}'],Path(d)/'out.png',5)
                self.assertEqual(model.image_model_stats()['attempts'],{})
            finally:model.close()
        edit.assert_not_called();run.assert_not_called()

    def test_unknown_paid_image_failure_never_triggers_adapter_resubmission(self):
        a=self.agent();import pop_repair
        from heideng_merchant.mature_image import MerchantImageClient
        with tempfile.TemporaryDirectory() as d,patch.object(MerchantImageClient,'edit',side_effect=RuntimeError('synthetic unknown output')) as edit,patch('subprocess.run') as run:
            model=a.ModelClient('synthetic');model.max_model_requests=2
            try:
                with self.assertRaises(a.JdoWriteUncertainError):
                    pop_repair.request_repair_image(a,model,'white','unchanged prompt',Path(d)/'ref.jpg',['JoyAgent-image(JoyAgent)','{reference}','{output}','{prompt}'],Path(d)/'out.png',5)
                with self.assertRaises(a.JdoWriteUncertainError):
                    pop_repair.request_repair_image(a,model,'white','unchanged prompt',Path(d)/'ref.jpg',['JoyAgent-image(JoyAgent)','{reference}','{output}','{prompt}'],Path(d)/'out.png',5)
                self.assertEqual(sum(model.image_model_stats()['attempts'].values()),1)
            finally:model.close()
        edit.assert_called_once();run.assert_not_called()

    def test_received_paid_image_bytes_are_reused_without_another_model_request(self):
        a=self.agent();import pop_repair
        from heideng_merchant.mature_image import MerchantImageClient
        with tempfile.TemporaryDirectory() as d,patch.object(MerchantImageClient,'edit',return_value=b'synthetic-image') as edit:
            model=a.ModelClient('synthetic');model.max_model_requests=1
            try:
                arguments=(a,model,'white','unchanged prompt',Path(d)/'ref.jpg',None,Path(d)/'out.png',5)
                self.assertEqual(pop_repair.request_repair_image(*arguments),b'synthetic-image')
                self.assertEqual(pop_repair.request_repair_image(*arguments),b'synthetic-image')
            finally:model.close()
        edit.assert_called_once()

    def test_reference_override_cannot_bypass_an_unknown_paid_receipt_for_same_slots(self):
        a=self.agent();import pop_repair
        receipt={'status':'unknown','repairScope':{'spuId':'11','kind':'white','skuIds':['1','2']}}
        with self.assertRaises(a.JdoWriteUncertainError):pop_repair.assert_no_unresolved_images([receipt],'11','transparent',['2'],a)
        pop_repair.assert_no_unresolved_images([receipt],'11','scene1',['2'],a)
        pop_repair.assert_no_unresolved_images([receipt],'22','white',['3'],a)

    def test_live_approved_slot_is_not_regenerated_from_an_old_rejected_snapshot(self):
        a=self.agent();import pop_repair
        identity={'shopName':'fixture','venderId':'123','shopId':'123'}
        row={'skuId':'1','productId':'11','skuName':'fixture','slots':{'white':{'state':'rejected','auditReasons':['模糊']}}}
        old={**a._binding_material(31,1,'https://img14.360buyimg.com/imgzone/jfs/old.jpg','1'),'status':5}
        current={**a._binding_material(31,1,'https://img14.360buyimg.com/imgzone/jfs/approved.jpg','1'),'status':4}
        client=Mock();client.seller_info.return_value=identity;client.resolve_category.return_value=1
        model=Mock();model.image_model_stats.return_value={'usage':{},'attempts':{}}
        cases=[([current],'approved'),([{**current,'status':3}],'pending'),([{**old,'auditDesc':'禁止出现文字信息'}],'skipped-changed'),([old,{**old,'imageMaterial':current['imageMaterial']}],'skipped-changed')]
        for live,expected in cases:
          with self.subTest(expected=expected,live=live),tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_LTS4AI_API_KEY':'synthetic','HEIDENG_MERCHANT_HOME':d},clear=True):
            root=Path(d);(root/'repair-scope.json').write_text(json.dumps({'shopIdentity':identity,'rows':[row],'skuSources':{'1':{'logo':'https://img14.360buyimg.com/imgzone/jfs/ref.jpg'}},'originals':{'1':[old]}}))
            args=Namespace(output_dir=root,profile='fixture',expected_shop_name='fixture',confirm='AUTO_MAINTAIN',repair_kind=['white'],paid_generation=True,jingmai_first=False,jingmai_ledger=root/'ledger.json',max_model_requests=1)
            def download(_url,path,*_args):
                from PIL import Image
                path.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(800,800),'white').save(path,'JPEG')
            with patch.object(a,'JdoClient',return_value=client),patch.object(a,'ModelClient',return_value=model),patch.object(a,'_query_binding_materials',return_value={'1':live}),patch.object(a,'_download_reference',side_effect=download),patch.object(a,'request_material_image',return_value=b'fixture') as image,patch('heideng_merchant.mature_runtime.registered_browser_profile',return_value=None):
                from tests.test_audit_handoff_contracts import run_approved_repair
                result=run_approved_repair(args,a)
          image.assert_not_called();client.bind_sku_materials.assert_not_called();self.assertEqual(result['rows'][0]['status'],expected)

if __name__=='__main__':unittest.main()
