"""POP mature source boundary tests; no actual merchant import or generation."""
import importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'mature/materials'

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,file);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

class MatureMaterialsTests(unittest.TestCase):
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
        self.assertEqual(a.PROVIDER.image_model,'gpt-image-2.5')
        self.assertEqual(a.PROVIDER.base_url,'https://api.lts4ai.com/v1')
        self.assertEqual(a.PROVIDER.api_key_env,'HEIDENG_MERCHANT_LTS4AI_API_KEY')
    def test_company_fallback_is_removed_not_silently_used(self):
        import pop_repair
        with self.assertRaises(RuntimeError):pop_repair.install_joyagent_fallback(object(),[],Path('fixture'))

if __name__=='__main__':unittest.main()
