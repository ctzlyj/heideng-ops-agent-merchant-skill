"""Regression evidence for merchant adaptations only. No business/network writes."""
import ast, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from tests.test_mature_materials import MatureMaterialsTests, SOURCE, ROOT

class UsabilityTests(MatureMaterialsTests):
    def fixture(self, a):
        rows=tuple(a.SourceRow(str(i), '纯棉保暖上衣', str(i), '60') for i in (11,22))
        jobs=tuple(a.SpuJob(r.spu_id,r.sku_id,r.title,(r.sku_id,),((r.sku_id,r.title),),(),False,False,False,False,False) for r in rows)
        return a.PreparedSource('jdo-pop','fixture',('SKUID','商品名称','SPUID'),rows,jobs,2,0,0)

    def test_frozen_whole_shop_plan_accepts_same_shop_subset_without_rewriting_hash(self):
        a=self.agent();seller={'shopName':'fixture','venderId':'1','shopId':'2'}
        with tempfile.TemporaryDirectory() as d:
            prepared=self.fixture(a);source=a._write_jdo_source(prepared,Path(d)/'source.xlsx')
            path=a.write_pop_auto_maintain_plan(prepared,{'11':'jfs/a.jpg','22':'jfs/b.jpg'},{},seller,d,source,target_spu_id=None)
            before=path.read_bytes()
            subset,refs,_,_=a.load_pop_auto_maintain_plan(d,seller,'11')
            self.assertEqual([r.spu_id for r in subset.rows],['11']);self.assertEqual(set(refs),{'11'})
            self.assertEqual(path.read_bytes(),before)
            with self.assertRaises(ValueError):a.load_pop_auto_maintain_plan(d,seller,'99')
            with self.assertRaises(ValueError):a.load_pop_auto_maintain_plan(d,{**seller,'venderId':'different'},'11')

    def test_low_score_does_not_assume_every_slot_missing(self):
        a=self.agent()
        class Client:
            def seller_info(self):return {'success':True,'isPop':True,'active':True,'shopName':'fixture'}
            def health_infos(self,page,size):return {'items':[{'skuId':'11','healthScore':60}], 'totalItems':1,'pageNum':page}
            def online_products(self,page,size):return {'items':[{'productId':'11','logo':'jfs/a.jpg'}], 'totalItems':1,'pageNum':page}
            def skus(self,ids):return [{'productId':'11','skuId':'11','skuName':'纯棉上衣','status':103}]
        with patch.object(a,'inspect_unscored_materials',return_value=({'11':{'scene1'}},{'11':{'uploaded_urls':{'white':'approved'}}})) as inspect:
            prepared,_,existing=a.discover_jdo_pop_source(Client())
        self.assertEqual(inspect.call_args.args[1][0]['skuId'],'11')
        job=prepared.jobs[0];self.assertFalse(job.needs_white);self.assertFalse(job.needs_selling_image)
        self.assertTrue(job.needs_scenes);self.assertEqual(existing['11']['uploaded_urls']['white'],'approved')

    def test_detail_reference_uses_material_main_images_and_representative_sku(self):
        a=self.agent()
        self.assertEqual(a.product_reference_url({'material':{'mainImages':['jfs/main.jpg']}},'11'),'https://img14.360buyimg.com/imgzone/jfs/main.jpg')
        self.assertIn('own.jpg',a.product_reference_url({'skuList':[{'skuId':'22','logo':'jfs/other.jpg'},{'skuId':'11','logo':'jfs/own.jpg'}]},'11'))
        with self.assertRaises(ValueError):a.product_reference_url({'material':{'mainImages':['https://untrusted.invalid/a.jpg']}},'11')

    def test_reference_download_supplies_public_headers_without_credentials(self):
        a=self.agent()
        from PIL import Image
        from io import BytesIO
        b=BytesIO();Image.new('RGB',(30,30)).save(b,'JPEG')
        response=SimpleNamespace(url='https://img14.360buyimg.com/imgzone/jfs/a.jpg',content=b.getvalue(),raise_for_status=lambda:None)
        with tempfile.TemporaryDirectory() as d,patch.object(a.httpx,'get',return_value=response) as get:
            a._download_reference(str(response.url),Path(d)/'a.jpg',5)
        headers=get.call_args.kwargs['headers'];self.assertIn('User-Agent',headers);self.assertIn('Referer',headers)
        self.assertNotIn('Cookie',headers);self.assertNotIn('Authorization',headers)

    def test_attrs_exact_targets_do_not_inventory_entire_shop(self):
        self.agent();import pop_attrs
        client=Mock()
        client._get.return_value={'data':{'productInfo':{'productName':'fixture','categoryDetail':{},'goodsAttrInfos':[]}}}
        with patch.object(pop_attrs,'template_attrs',return_value=[]):
            plan=pop_attrs.inventory(client,{'shopName':'fixture'},product_ids=['11'])
        self.assertEqual(plan['productCount'],1)
        self.assertFalse(any(call.args[1]=='/rest/sp-product/v0/products' for call in client._get.call_args_list))

    def test_reconcile_wrong_directory_is_not_an_empty_success(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'目录|directory'):a.reconcile_run_receipts(Mock(),d)

    def test_owned_edge_profile_is_not_launched_in_chrome(self):
        self.agent();import pop_browser
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
            profile=Path(d)/'browser-profiles'/'fixture';profile.mkdir(parents=True)
            (Path(d)/'linker').mkdir()
            (Path(d)/'linker/shops.json').write_text(json.dumps({'profiles':{'fixture':{'browserProfileDir':str(profile),'browserChannel':'msedge'}}}))
            browser=Mock();pop_browser._open(browser,str(profile))
            self.assertEqual(browser.chromium.launch_persistent_context.call_args.kwargs['channel'],'msedge')

    def test_bridge_override_is_validated_and_preserved_across_isolated_home(self):
        from heideng_merchant.mature_runtime import child_environment
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'python.exe';exe.write_bytes(b'fixture')
            env=child_environment(Path(d)/'merchant',{'HEIDENG_MERCHANT_PYTHON312':str(exe),'JD_LLM_API_KEY':'never-copy'})
            self.assertEqual(env['JDO_PYTHON312'],str(exe.resolve()));self.assertNotIn('JD_LLM_API_KEY',env)

    def test_workbuddy_install_has_independent_host_target(self):
        import install
        self.assertEqual(install.target_directory('workbuddy','C:/fixture').parts[-3:],('.workbuddy','skills','heideng-ops-agent-merchant'))

    def test_live_lock_blocks_and_dead_legacy_owner_does_not_delete_unknown_receipt(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'.state';state.mkdir()
            receipt=state/'task.json';receipt.write_text('{"status":"unknown"}')
            with a.pop_execution_lock(root):
                with self.assertRaises(a.JdoWriteUncertainError):
                    with a.pop_execution_lock(root):pass
            (state/'pop-execution.lock').write_text(json.dumps({'pid':2147483646,'token':'dead-fixture'}))
            with a.pop_execution_lock(root):self.assertEqual(receipt.read_text(),'{"status":"unknown"}')
            self.assertEqual(receipt.read_text(),'{"status":"unknown"}')

    def test_satisfied_title_rows_are_ignored_but_outside_shop_scope_is_rejected(self):
        a=self.agent();prepared=self.fixture(a)
        text={'selling_points':{},'short_titles':{'11':'纯棉保暖圆领上衣'}}
        self.assertEqual(a._validate_agent_text_scope(text,prepared)['short_titles'],{})
        with self.assertRaisesRegex(ValueError,'99'):a._validate_agent_text_scope({'selling_points':{},'short_titles':{'99':'无关商品'}},prepared)

    def test_host_attribute_evidence_uses_existing_enum_validation(self):
        self.agent();import pop_attrs
        client=Mock();client._get.return_value={'data':{'productInfo':{'productName':'fixture','categoryDetail':{'lastCategoryId':1}}}}
        attr={'title':'材质','code':'material','inputType':'singleSelect','required':False,'important':True,'options':[{'label':'棉','value':'1'}]}
        with patch.object(pop_attrs,'_schema_payload',return_value=[]),patch.object(pop_attrs,'template_attrs',return_value=[attr]),patch.object(pop_attrs,'build_patch',return_value=({},{})):
            plan=pop_attrs.inventory(client,{},product_ids=['11'],agent_choices={'11':{'evidence':'用户商品规格注明纯棉','choices':[{'title':'材质','n':[0],'confidence':'high'}]}})
            self.assertEqual(plan['plans'][0]['autoFill']['材质']['value'],'1')
            with self.assertRaises(ValueError):pop_attrs.inventory(client,{},product_ids=['11'],agent_choices={'99':{'evidence':'fixture','choices':[]}})

    def test_auto_tail_repair_attrs_and_readbacks_use_same_selected_scope(self):
        from contextlib import ExitStack
        a=self.agent();import pop_workflow,pop_repair,pop_attrs
        seller={'shopName':'fixture','venderId':'1','shopId':'2','success':True,'isPop':True,'active':True}
        with tempfile.TemporaryDirectory() as d,ExitStack() as stack:
            prepared=self.fixture(a);source=a._write_jdo_source(prepared,Path(d)/'source.xlsx')
            a.write_pop_auto_maintain_plan(prepared,{}, {},seller,d,source,target_spu_id=None)
            args=a.build_parser().parse_args(['auto-maintain','--profile','fixture','--expected-shop-name','fixture','--output-dir',d,'--target-spu-id','11','--include-full-score','--confirm','AUTO_MAINTAIN'])
            client=Mock();client.seller_info.return_value=seller;client.resolve_category.return_value=1
            stack.enter_context(patch.object(a,'JdoClient',return_value=client))
            stack.enter_context(patch.object(a,'generate_batch',return_value=SimpleNamespace(completed_spus=1,failed_spus=[],manifest_path=None)))
            get=stack.enter_context(patch.object(a,'_download_reference'))
            stack.enter_context(patch.object(a,'pending_cutout_handoff',return_value=[]))
            stack.enter_context(patch.object(pop_workflow,'finish_external_images',return_value={'blocked':[]}))
            stack.enter_context(patch.object(a,'export_short_title_delivery',return_value={'status':'no-titles','shortTitleFiles':[]}))
            stack.enter_context(patch.object(pop_workflow,'complete_short_title_import',return_value={'status':'no-titles','shortTitleFiles':[]}))
            repair=stack.enter_context(patch.object(pop_repair,'run_rejected_repairs',return_value={'status':'no-rejections'}))
            attrs=stack.enter_context(patch.object(pop_attrs,'inventory',return_value={'plans':[],'needsConfirmation':[]}))
            audit=stack.enter_context(patch.object(a,'audit_pop_coverage',return_value={'rows':[],'shortTitleIssueSkuIds':[],'issueCounts':{}}))
            result=a.run_auto_maintain(args)
            self.assertEqual(result['spuCount'],1);self.assertEqual(repair.call_args.args[0].authorized_sku_ids,['11'])
            self.assertEqual(attrs.call_args.kwargs['product_ids'],['11'])
            self.assertEqual(audit.call_args.kwargs['product_ids'],['11']);self.assertEqual(audit.call_args.kwargs['authorized_sku_ids'],['11'])
            get.assert_not_called();self.assertEqual(result['batches'][0]['referenceFailures'],[]);client.resolve_category.assert_not_called()

    def test_short_title_json_duplicate_keys_fail_instead_of_silent_overwrite(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'host.json';path.write_text('{"shortTitles":{"11":"first","11":"second"}}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'重复|duplicate'):a.load_agent_text(path)

    def test_large_results_use_task_file_and_small_stdout_summary(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            payload={'status':'waiting-review','skuCount':299,'batches':[{'rows':['detail']*10000}]}
            summary=a.merchant_result_summary(payload,d,'auto-maintain')
            self.assertLess(len(json.dumps(summary)),2000)
            self.assertEqual(json.loads(Path(summary['resultFile']).read_text(encoding='utf-8')),payload)

    def test_explicit_discovery_does_not_lookup_unrelated_product_skus(self):
        a=self.agent()
        class Client:
            def seller_info(self):return {'success':True,'isPop':True,'active':True,'shopName':'fixture'}
            def health_infos(self,page,size):return {'items':[{'skuId':'11','healthScore':60},{'skuId':'22','healthScore':50}], 'totalItems':2,'pageNum':page}
            def online_products(self,page,size):return {'items':[{'productId':'11','logo':'jfs/a.jpg'},{'productId':'22','logo':'jfs/b.jpg'}], 'totalItems':2,'pageNum':page}
            def skus(self,ids):
                if ids!=['11']:raise AssertionError('single-product discovery requested unrelated SKUs')
                return [{'productId':'11','skuId':'11','skuName':'纯棉上衣','status':103}]
        with patch.object(a,'inspect_unscored_materials',return_value=({'11':{'scene1'}},{})):
            prepared,_,_=a.discover_jdo_pop_source(Client(),scope_spu_ids=['11'])
        self.assertEqual([r.sku_id for r in prepared.rows],['11'])

    def test_host_reclaimed_process_releases_os_lock_and_preserves_unknown_data(self):
        import time
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);receipt=root/'unknown.json';receipt.write_text('{"status":"unknown"}')
            # A Windows venv launcher may have a different PID from the lock owner.
            # Closing the harness pipe crashes the actual worker without unwinding its lock.
            code="""import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
import jd_material_agent as a
root = Path(sys.argv[1])
with a.pop_execution_lock(root):
    (root / 'ready').write_text('ready')
    sys.stdin.buffer.read(1)
    os._exit(23)
"""
            proc=subprocess.Popen([sys.executable,'-c',code,str(root),str(SOURCE/'scripts')],cwd=ROOT,
                                  stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+5
                while not (root/'ready').exists() and proc.poll() is None and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue((root/'ready').exists())
                proc.stdin.close()
                self.assertEqual(proc.wait(timeout=5), 23)
                with a.pop_execution_lock(root):self.assertEqual(receipt.read_text(),'{"status":"unknown"}')
            finally:
                proc.stdin.close()
                if proc.poll() is None:proc.wait(timeout=5)
                if proc.stderr:proc.stderr.close()

    def test_frozen_subset_keeps_original_batch_number_and_other_job_unknown_state(self):
        a=self.agent();seller={'shopName':'fixture','venderId':'1','shopId':'2'}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);full=self.fixture(a);source=a._write_jdo_source(full,root/'source.xlsx')
            a.write_pop_auto_maintain_plan(full,{}, {},seller,root,source,target_spu_id=None)
            subset,_,_,_=a.load_pop_auto_maintain_plan(root,seller,'22')
            batches=list(a.frozen_scope_batches(subset,root))
            self.assertEqual([i for i,_ in batches],[1])
            unknown=root/'批次001/.state/task.json';unknown.parent.mkdir(parents=True);unknown.write_text('{"status":"unknown","otherShopReceipt":true}')
            self.assertEqual(unknown.read_text(),'{"status":"unknown","otherShopReceipt":true}')
            with patch.object(a,'MAX_SPUS_PER_BATCH',1):
                self.assertEqual([i for i,_ in a.frozen_scope_batches(subset,root)],[2])

    def test_image_prompts_are_ast_identical_to_delivered_baseline(self):
        text=(SOURCE/'scripts/jd_material_agent.py').read_text(encoding='utf-8')
        before=subprocess.check_output(['git','show','b5b4a27:mature/materials/scripts/jd_material_agent.py'],cwd=ROOT).decode('utf-8')
        def selected(s):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(s).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in ('_shared_image_rules','image_prompt')}
        self.assertEqual(selected(text),selected(before));self.assertEqual(len(selected(text)),2)

if __name__=='__main__':unittest.main()
