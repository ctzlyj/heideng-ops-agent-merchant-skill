"""POP mature source boundary tests; no actual merchant import or generation."""
import importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'mature/materials'

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,file);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

class MatureMaterialsTests(unittest.TestCase):
    def test_identity_only_material_read_is_distinct_from_an_unreported_sku(self):
        agent=self.agent()
        client=agent.JdoClient('fixture')
        def query(skill,url,params):
            if params['scopeSet']==[2]:
                return {'success':True,'data':[{'skuId':sid,'materials':[]} for sid in params['skuIds']]}
            return {'success':True,'data':[{'skuId':11},{'skuId':12,'errorCode':'NOT_VISIBLE'}]}
        with patch.object(client,'_get',side_effect=query):
            gaps={}
            items=agent._query_binding_materials(client,['11','12','13'],read_gaps=gaps)
            self.assertEqual(items,{'11':[],'12':[],'13':[]})
            self.assertEqual(gaps,{'12':[31,32,33,36],'13':[31,32,33,36]})
            with self.assertRaisesRegex(ValueError,'incomplete'):
                agent._query_binding_materials(client,['11','12','13'])
    def setUp(self):
        self.path=list(sys.path);sys.path.insert(0,str(SOURCE/'scripts'))
        self.names=('jd_material_agent','pop_attrs','pop_browser','pop_cutout','pop_repair','pop_safety','pop_text','pop_workflow','jdo_bridge_probe')
        self.saved={x:sys.modules.pop(x,None) for x in self.names}
    def tearDown(self):
        sys.path[:]=self.path
        for x in self.names:
            sys.modules.pop(x,None)
            if self.saved[x] is not None:sys.modules[x]=self.saved[x]
    def agent(self):return load('jd_material_agent',SOURCE/'scripts/jd_material_agent.py')
    def test_pop_uses_only_registry_profile_bound_to_same_verified_shop(self):
        from heideng_merchant.mature_runtime import registered_browser_profile
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
            state=Path(d);directory=state/'browser-profiles'/'fixture';directory.mkdir(parents=True)
            (state/'linker').mkdir()
            record={'profiles':{'fixture-profile':{'shopName':'fixture-shop','venderId':'12345','shopId':'67890','browserProfileDir':str(directory)}}}
            (state/'linker/shops.json').write_text(json.dumps(record))
            identity={'shopName':'fixture-shop','venderId':'12345','shopId':'67890'}
            self.assertEqual(registered_browser_profile('fixture-profile',identity),directory.resolve())
            self.assertIsNone(registered_browser_profile('fixture-profile',{**identity,'venderId':'unrelated-shop'}))
            self.assertIsNone(registered_browser_profile('missing-profile',identity))
            record['profiles']['fixture-profile']['browserProfileDir']=str(state.parent)
            (state/'linker/shops.json').write_text(json.dumps(record))
            self.assertIsNone(registered_browser_profile('fixture-profile',identity))

    def test_actual_auto_import_uses_owned_profile_metadata_without_new_title_runtime(self):
        from argparse import Namespace
        from heideng_merchant.mature_runtime import registered_browser_profile
        a=self.agent();import pop_browser,pop_workflow
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
            root=Path(d);directory=root/'browser-profiles'/'fixture';directory.mkdir(parents=True)
            (root/'linker').mkdir()
            seller={'shopName':'fixture-shop','venderId':'12345','shopId':'67890'}
            (root/'linker/shops.json').write_text(json.dumps({'profiles':{'fixture-profile':{**seller,'browserProfileDir':str(directory)}}}))
            workbook=root/'titles.xlsx';workbook.write_bytes(a._short_title_workbook_bytes([('1234567890','保暖纯棉圆领长袖上衣')]))
            args=Namespace(profile='fixture-profile',output_dir=root)
            receipt={'status':'import-completed','creationAccepted':True,'taskId':'fixture-only','successRows':1,'failedRows':0}
            with patch.object(pop_browser,'import_short_titles',return_value=receipt) as importer,patch.object(a,'audit_pop_coverage',return_value={'rows':[{'skuId':'1234567890'}]}):
                result=pop_workflow.complete_short_title_import(args,{'shortTitleFiles':[str(workbook)],'rowCount':1},seller,object(),agent=a)
            self.assertEqual(importer.call_args.args[0],str(directory.resolve()))
            self.assertEqual(importer.call_count,1)
            self.assertTrue(result['platformTitleImportVerified'])
            self.assertFalse(result['manualImportRequired'])

    def test_real_agent_entrypoint_and_title_template_are_packaged(self):
        from heideng_merchant.mature_runtime import source_path
        path,meta=source_path('materials');self.assertEqual(path,SOURCE/'scripts/jd_material_agent.py')
        self.assertEqual(meta['upstreamCommit'],'b56b22376db88182352d3f64ea3e9752d4ae5677')
        self.assertTrue((SOURCE/'assets/商品导入短标题模板.xlsx').is_file())

    def test_targeted_title_export_uses_the_original_frozen_batch_in_a_separate_destination(self):
        a = self.agent()
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / 'original'
            run.mkdir()
            output = Path(d) / 'delivery'
            source = run / 'source.xlsx'
            source.write_bytes(b'fixture source')
            rows = (a.SourceRow('101', 'first', '201'), a.SourceRow('102', 'other', '202'))
            jobs = tuple(a.SpuJob(row.spu_id, row.sku_id, row.title, (row.sku_id,),
                                  ((row.sku_id, row.title),), (row.sku_id,)) for row in rows)
            full = a.PreparedSource('jdo-pop', 'Sheet1', (), rows, jobs, 2, 0, 0)
            identity = {'shopName': 'fixture', 'shopId': '801', 'venderId': '802'}
            a.write_pop_auto_maintain_plan(full, {}, {}, identity, run, source, target_spu_id=None)
            scoped = a._subset_prepared(full, [rows[0]])
            batch = run / '批次001'
            state_path = batch / '.state' / 'task.json'
            state = a._load_state(state_path)
            a._bind_state(state, scoped, state_path)
            self.assertEqual(state['task_signature'], a._task_signature(full))
            title = '保暖纯棉圆领长袖上衣'
            state['jobs']['201']['short_titles'] = {'101': title}
            a._save_state(state_path, state)
            workbook = batch / '商品导入短标题模板_已回填.xlsx'
            workbook.write_bytes(a._short_title_workbook_bytes([('101', title)]))
            result = a.export_short_title_delivery([(scoped, run)], output, shop_name='fixture')
            self.assertEqual(result['rowCount'], 1)
            self.assertEqual(Path(result['shortTitleFiles'][0]).parent, output)

    def test_missing_selling_point_uses_the_whole_group_and_keeps_approved_values(self):
        a = self.agent()
        from pop_safety import missing_only_requests
        sku = '101'
        job = a.SpuJob('201', sku, 'fixture', (sku,), ((sku, 'fixture'),),
                       needs_white=False, needs_scenes=False, needs_selling_image=False, needs_transparent=False)
        request = a.build_material_binding_requests(job, {'selling_points': ['原案设想', '室内使用', '便携移动']})
        old = {**a._binding_material(1002, 1, '原已通过', sku), 'status': 4}
        group = missing_only_requests(request, {sku: [old]})[0]
        materials = group['body']['skuMaterials'][0]['materials']
        self.assertEqual([a._material_value(item) for item in materials], ['原已通过', '室内使用', '便携移动'])
        actual = [{**item, 'status': 4} for item in materials]
        self.assertEqual(a._evaluate_binding_request(group, {sku: actual})[0], 'approved')
        self.assertEqual(missing_only_requests(request, {sku: [{**old, 'status': 3}]}), [])
    def test_pop_title_workbook_validation_retains_mature_contract(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'title.xlsx';path.write_bytes(a._short_title_workbook_bytes([('1234567890','保暖纯棉圆领长袖上衣')]))
            result=a.validate_short_title_workbook(path)
        self.assertTrue(result['valid'],result)
    def test_original_automatic_title_import_workflow_remains_present(self):
        source=(SOURCE/'scripts/pop_workflow.py').read_text(encoding='utf-8')
        self.assertIn('def complete_short_title_import(',source)
        self.assertIn('import_short_titles',source)
        self.assertIn('platformTitleImportVerified',source)
        self.assertNotIn('short_title_worker',source)
    def test_image_call_uses_existing_sufy_adapter_once_even_on_error(self):
        a=self.agent()
        from heideng_merchant.mature_image import MerchantImageClient
        from heideng_merchant.safety import SafetyError
        with patch.object(MerchantImageClient,'edit',side_effect=SafetyError('unknown-output')) as edit:
            client=a.ModelClient('offline-fixture-not-a-secret')
            try:
                with self.assertRaises(SafetyError):client.edit_image('fixture',Path('fixture.png'),model='pool')
            finally:client.close()
        self.assertEqual(edit.call_count,1)
    def test_unconfigured_text_and_vision_stop_before_http(self):
        a=self.agent();import pop_text,pop_attrs
        with patch('httpx.Client',side_effect=AssertionError('unconfigured channel must not open HTTP')):
            with self.assertRaises(RuntimeError):pop_text.TextPool('offline-fixture')
            with self.assertRaises(RuntimeError):pop_attrs.VisionAttrModel('offline-fixture')
        self.assertEqual(a.PROVIDER.image_model,a.MODELS[0])
        self.assertEqual(tuple(name for name,_ in a.PROVIDER.image_model_pool),a.MODELS)
        self.assertEqual(a.PROVIDER.base_url,'https://api.lts4ai.com/v1')
        self.assertEqual(a.PROVIDER.api_key_env,'HEIDENG_MERCHANT_LTS4AI_API_KEY')
    def test_existing_uploaded_white_still_derives_missing_transparent_without_model_call(self):
        a=self.agent()
        job=a.SpuJob('123456','123','fixture',('123',),(('123','fixture'),),needs_selling_points=False,needs_white=False,needs_scenes=False,needs_selling_image=False,needs_transparent=True)
        row=a.SourceRow('123','fixture','123456')
        prepared=a.PreparedSource('fixture','fixture',(),(row,),(job,),1,1,0)
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)
            existing={'123456':{'uploaded_urls':{'white':'https://img14.360buyimg.com/imgzone/fixture-white.jpg'}}}
            def restore(_url,path,_timeout):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'white')
            def derive(_source,path):path.write_bytes(b'transparent')
            with patch.object(a,'valid_material_image',side_effect=lambda path,_kind:Path(path).exists()),patch.object(a,'restore_uploaded_white',side_effect=restore) as restored,patch.object(a,'make_transparent',side_effect=derive) as transparent:
                result=a.generate_batch(prepared,output/'references',output,existing_materials=existing)
            self.assertEqual(result.failed_spus,0);self.assertEqual(result.completed_spus,1)
            restored.assert_called_once();transparent.assert_called_once()

    def test_external_cutout_single_spu_target_is_passed_to_frozen_plan(self):
        from argparse import Namespace
        a=self.agent()
        class ExpectedStop(Exception):pass
        seller={'shopName':'fixture-shop','venderId':'12345','shopId':'67890'}
        client=Mock();client.seller_info.return_value=seller
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
            args=Namespace(confirm='AUTO_MAINTAIN',output_dir=Path(d),profile='fixture-profile',expected_shop_name=None,target_spu_id='123456')
            with patch.object(a,'assert_no_unknown_uploads'),patch.object(a,'JdoClient',return_value=client),patch.object(a,'load_pop_auto_maintain_plan',side_effect=ExpectedStop) as plan:
                with self.assertRaises(ExpectedStop):a.run_bind_external_cutouts(args)
            self.assertEqual(plan.call_args.args[2],'123456')

    def test_existing_oversized_reference_is_normalized_before_any_model_request(self):
        from PIL import Image
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'123456.jpg';Image.new('RGB',(950,950),(240,240,240)).save(path,'JPEG')
            a._download_reference('https://img14.360buyimg.com/imgzone/fixture.jpg',path,1)
            with Image.open(path) as image:self.assertEqual(image.size,(800,800))

    def test_unknown_write_returns_original_task_recovery_command_in_chinese(self):
        from argparse import Namespace
        a=self.agent()
        try:payload=a._unknown_write_payload(Namespace(output_dir=Path('original-task'),profile='fixture-profile'))
        except AttributeError as error:self.fail(f'未知写入需要可见恢复入口：{error}')
        self.assertEqual(payload['status'],'paused-unknown-write')
        self.assertIn('原任务',payload['nextAction']);self.assertIn('不要重复提交',payload['nextAction'])
        self.assertIn('reconcile-receipts',payload['recoveryCommand'])
        self.assertIn('--profile fixture-profile',payload['recoveryCommand'])
        self.assertIn('original-task',payload['recoveryCommand'])


    def test_company_fallback_is_removed_not_silently_used(self):
        import pop_repair
        with self.assertRaises(RuntimeError):pop_repair.install_joyagent_fallback(object(),[],Path('fixture'))

if __name__=='__main__':unittest.main()
