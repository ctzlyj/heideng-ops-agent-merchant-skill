"""Task-local host prompts are real inputs, not changes to the mature default template."""
import io,json,tempfile,unittest,os,hashlib
from contextlib import redirect_stdout
from pathlib import Path
from argparse import Namespace
from unittest.mock import Mock,patch
import tests.test_mature_materials as helpers

class TaskImagePromptTests(unittest.TestCase):
    setUp=helpers.MatureMaterialsTests.setUp
    tearDown=helpers.MatureMaterialsTests.tearDown
    agent=helpers.MatureMaterialsTests.agent

    def test_model_request_receives_host_prompt_instead_of_appending_default_rules(self):
        a=self.agent();custom='完整商品居中留白，保留商品印刷；不增加额外标签。'
        with patch.object(a,'request_material_image',return_value=b'fixture') as call:
            try:result,errors=a._request_image_set(Mock(),['white'],Path('fixture.jpg'),'fixture',prompts={'white':custom})
            except TypeError as error:self.fail('生图没有任务级提示词入口：'+str(error))
        self.assertFalse(errors);self.assertEqual(result['white'],b'fixture');self.assertEqual(call.call_args.args[2],custom)

    def test_all_actual_generation_entrypoints_offer_task_prompt_file(self):
        a=self.agent();commands=a.build_parser()._subparsers._group_actions[0].choices
        for name in ('generate','generate-auto-maintain','auto-maintain','repair-rejected'):
            with self.subTest(command=name):
                flags={option for action in commands[name]._actions for option in action.option_strings}
                self.assertIn('--image-prompts-file',flags)

    def test_prompt_file_scope_and_duplicate_keys_are_checked_before_model(self):
        a=self.agent();self.assertTrue(hasattr(a,'load_image_prompts'),'缺少宿主提示词文件加载')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'prompts.json';path.write_text(json.dumps({'11':{'white':'完整新提示词'}}),encoding='utf-8')
            value=a.load_image_prompts(path,['11']);self.assertEqual(value['11']['white']['prompt'],'完整新提示词')
            for content in ('{"22":{"white":"x"}}','{"11":{"invalid":"x"}}','{"11":{"white":""}}','{"11":{"white":"a","white":"b"}}'):
                path.write_text(content,encoding='utf-8')
                with self.assertRaises(ValueError):a.load_image_prompts(path,['11'])

    def test_reviewed_added_text_can_be_redesigned_but_product_printing_is_not_erased(self):
        self.agent();import pop_repair
        slot={'auditReasons':['禁止出现文字信息']};url='https://img14.360buyimg.com/imgzone/jfs/fixture.jpg'
        override={'prompt':'去除模型额外加的标题贴片，保留真实商品印刷','textOrigin':'generated','evidence':'已查看驳回图，额外文字浮在背景上','rejectedImageUrl':url}
        try:appeal=pop_repair.product_text_appeal('white',slot,override,current_url=url)
        except TypeError as error:self.fail('审核原因被机械等同为商品印刷，无法由Agent依据看图证据纠正：'+str(error))
        self.assertFalse(appeal)
        self.assertTrue(pop_repair.product_text_appeal('white',slot,{**override,'textOrigin':'product'},current_url=url))
        self.assertTrue(pop_repair.product_text_appeal('white',slot,override,current_url=url+'-changed'))

    def test_real_generate_batch_passes_scoped_host_prompt(self):
        a=self.agent();custom='任务构图：保留参考商品完整轮廓与印刷，背景纯白。'
        job=a.SpuJob('11','1','fixture',('1',),(('1','fixture'),),needs_selling_points=False,needs_scenes=False,needs_selling_image=False,needs_transparent=False)
        prepared=a.PreparedSource('fixture','Sheet1',(),(a.SourceRow('1','fixture','11'),),(job,),1,1,0)
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(800,800),'white').save(image,'JPEG')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);refs=root/'refs';refs.mkdir();(refs/'11.jpg').write_bytes(image.getvalue())
            client=Mock();client.image_model_stats.return_value={};client.text_model_stats.return_value={}
            with patch.object(a,'request_material_image',return_value=image.getvalue()) as call:
                try:result=a.generate_batch(prepared,refs,root/'out',model_client_factory=lambda:client,image_prompts={'11':{'white':{'prompt':custom}}})
                except TypeError as error:self.fail('批次入口没有传递任务提示词：'+str(error))
            self.assertEqual(result.failed_spus,0);self.assertEqual(call.call_args.args[2],custom)

    def test_generate_cli_reads_the_host_file_and_passes_it_to_the_real_batch_entry(self):
        a=self.agent();job=a.SpuJob('11','1','fixture',('1',),(('1','fixture'),))
        prepared=a.PreparedSource('fixture','Sheet1',(),(a.SourceRow('1','fixture','11'),),(job,),1,1,0)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);file=root/'prompts.json';file.write_text('{"11":{"white":"新的任务提示词"}}',encoding='utf-8')
            result=a.BatchResult(1,1,0,root,None,None,None)
            with patch.object(a,'_prepared_from_args',return_value=prepared),patch.object(a,'generate_batch',return_value=result) as batch,redirect_stdout(io.StringIO()):
                code=a.main(['generate','--source','fixture.xlsx','--reference-dir',d,'--output-dir',d,'--image-prompts-file',str(file)])
            self.assertEqual(code,0);self.assertEqual(batch.call_args.kwargs['image_prompts']['11']['white']['prompt'],'新的任务提示词')

    def test_unknown_shared_binding_is_reconciled_not_replayed_when_prompt_changes(self):
        a=self.agent();import pop_repair
        job=a.SpuJob('11','1','fixture',('1','2'),(('1','fixture'),('2','fixture')),needs_selling_points=False,needs_scenes=False,needs_selling_image=False,needs_transparent=False)
        request=a.build_material_binding_requests(job,{'uploaded_urls':{'white':'https://img14.360buyimg.com/imgzone/jfs/old.jpg'}})[0]
        client=Mock();client.sku_materials.return_value=[]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'shared-bindings';folder.mkdir();path=folder/'old.json';path.write_text(json.dumps({'status':'unknown','request':request}),encoding='utf-8')
            with self.assertRaises(a.JdoWriteUncertainError):pop_repair.reconcile_prompt_bindings(root,{'11':{'white':{'prompt':'new'}}},a,client)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['request'],request)
        client.bind_sku_materials.assert_not_called()

    def test_unclassified_text_rejection_goes_to_agent_visual_review_not_merchant_manual_work(self):
        a=self.agent();import pop_repair
        identity={'shopName':'fixture','venderId':'123','shopId':'123'};url='https://img14.360buyimg.com/imgzone/jfs/fixture.jpg'
        old={**a._binding_material(31,1,url,'1'),'status':5};row={'skuId':'1','productId':'11','skuName':'fixture','slots':{'white':{'state':'rejected','auditReasons':['禁止出现文字信息']}}}
        client=Mock();client.seller_info.return_value=identity
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{},clear=True):
            root=Path(d);(root/'repair-scope.json').write_text(json.dumps({'shopIdentity':identity,'rows':[row],'skuSources':{},'originals':{'1':[old]}}),encoding='utf-8')
            args=Namespace(output_dir=root,profile='fixture',expected_shop_name='fixture',confirm='AUTO_MAINTAIN',paid_generation=False,jingmai_first=False)
            with patch.object(a,'JdoClient',return_value=client),patch.object(a,'ModelClient') as model,patch('heideng_merchant.mature_image.merchant_key') as key,patch('heideng_merchant.mature_runtime.registered_browser_profile',return_value=None):result=pop_repair.run_rejected_repairs(args,a)
        self.assertEqual(result['status'],'needs-image-review');self.assertTrue(result['needsAgentAction']);self.assertFalse(result['needsMerchantAction'])
        self.assertEqual(result['imageReviewRequired'][0]['imageUrl'],url);model.assert_not_called();key.assert_not_called()
        from heideng_merchant.merchant_experience import task_summary
        self.assertIn('文字来源',task_summary(result)['message'])

    def test_explicit_model_refusal_is_known_failure_and_new_prompt_can_use_remaining_budget(self):
        a=self.agent();import pop_repair
        from heideng_merchant.mature_image import MerchantImageClient
        with tempfile.TemporaryDirectory() as d,patch.object(MerchantImageClient,'edit',side_effect=[a.ModelModerationBlocked('explicit content refusal'),b'fixture-image']) as edit:
            root=Path(d);model=a.ModelClient('synthetic');model.max_model_requests=2
            try:
                with self.assertRaises(a.ModelModerationBlocked):pop_repair.request_repair_image(a,model,'white','original prompt',root/'ref.jpg',None,root/'old.png',5)
                self.assertEqual(json.loads((root/'old.request.json').read_text(encoding='utf-8'))['status'],'rejected')
                with self.assertRaises(ValueError):pop_repair.request_repair_image(a,model,'white','original prompt',root/'ref.jpg',None,root/'old.png',5)
                self.assertEqual(pop_repair.request_repair_image(a,model,'white','host redesigned prompt',root/'ref.jpg',None,root/'new.png',5),b'fixture-image')
                self.assertEqual(sum(model.image_model_stats()['attempts'].values()),2)
            finally:model.close()
        self.assertEqual(edit.call_count,2)

    def test_current_host_guide_treats_default_as_starting_point_not_a_prohibition(self):
        root=Path(__file__).resolve().parents[1]
        skill=(root/'SKILL.md').read_text(encoding='utf-8');guide=(root/'references/experience-materials.md').read_text(encoding='utf-8')
        self.assertIn('默认提示词只是起点',skill)
        self.assertIn('--image-prompts-file',guide)
        self.assertNotIn('原生图提示词不改',guide);self.assertNotIn('通用和实际生图提示词仍不改',guide)

    def test_windows_utf8_bom_prompt_file_is_supported(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'prompts.json';file.write_text('{"11":{"white":"任务提示词"}}',encoding='utf-8-sig')
            self.assertEqual(a.load_image_prompts(file,['11'])['11']['white']['prompt'],'任务提示词')

    def test_evidence_metadata_does_not_create_another_identical_image_request(self):
        a=self.agent();entry={'prompt':'same actual design','evidence':'first review'}
        self.assertEqual(a.image_prompt_revision(entry,request_only=True),a.image_prompt_revision({**entry,'evidence':'updated review'},request_only=True))
        self.assertNotEqual(a.image_prompt_revision(entry),a.image_prompt_revision({**entry,'evidence':'updated review'}))

    def test_repair_uses_new_prompt_revision_without_overwriting_received_old_response(self):
        a=self.agent();import pop_repair
        custom='针对裁切驳回，完整商品缩小并居中，保留产品印刷，不放额外文字。'
        identity={'shopName':'fixture','venderId':'123','shopId':'123'}
        oldurl='https://img14.360buyimg.com/imgzone/jfs/old.jpg';newurl='https://img14.360buyimg.com/imgzone/jfs/new.jpg';ref='https://img14.360buyimg.com/imgzone/jfs/ref.jpg'
        from PIL import Image,ImageDraw
        def jpeg(color):
            im=Image.new('RGB',(800,800),'white');ImageDraw.Draw(im).rectangle((200,200,600,600),fill=color);out=io.BytesIO();im.save(out,'JPEG');return out.getvalue()
        newbytes=jpeg('blue');oldbytes=jpeg('red')
        for scenario in ('received-old-response','rejected-old-binding','unknown-old-response','already-pending','reviewed-added-text','reviewed-product-text'):
          with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_LTS4AI_API_KEY':'synthetic'},clear=True):
            old={**a._binding_material(31,1,oldurl,'1'),'status':5}
            row={'skuId':'1','productId':'11','skuName':'fixture','slots':{'white':{'state':'rejected','auditReasons':['裁切']}}}
            entry=custom
            if scenario in ('reviewed-added-text','reviewed-product-text'):
                row['slots']['white']['auditReasons']=['禁止出现文字信息'];old['auditDesc']='禁止出现文字信息'
                entry={'prompt':custom,'textOrigin':'generated' if scenario=='reviewed-added-text' else 'product','evidence':'已查看当前驳回图并核实文字来源','rejectedImageUrl':oldurl}
            root=Path(d);(root/'repair-scope.json').write_text(json.dumps({'shopIdentity':identity,'rows':[row],'skuSources':{'1':{'logo':ref}},'originals':{'1':[old]}}),encoding='utf-8')
            promptfile=root/'image-prompts.json';promptfile.write_text(json.dumps({'11':{'white':entry}}),encoding='utf-8')
            oldgroup=root/'shared'/hashlib.sha256(json.dumps(['11',ref],ensure_ascii=False).encode()).hexdigest()[:20];oldgroup.mkdir(parents=True)
            oldresponse=oldgroup/'white-adapter.request.json';saved={'status':'received','fingerprint':'old-input'}
            if scenario=='unknown-old-response':saved={'status':'unknown','fingerprint':'old-input','repairScope':{'spuId':'11','kind':'white','skuIds':['1']}}
            oldresponse.write_text(json.dumps(saved),encoding='utf-8');before=oldresponse.read_bytes()
            legacy=None;legacy_before=None
            current=old
            if scenario=='rejected-old-binding':
                priorurl='https://img14.360buyimg.com/imgzone/jfs/prior-rejected.jpg';current={**a._binding_material(31,1,priorurl,'1'),'status':5}
                job=a.SpuJob('11','1','fixture',('1',),(('1','fixture'),),needs_selling_points=False,needs_scenes=False,needs_selling_image=False,needs_transparent=False)
                request=a.build_material_binding_requests(job,{'uploaded_urls':{'white':priorurl}})[0]
                legacy=root/'1/white-binding.json';legacy.parent.mkdir();legacy.write_text(json.dumps({'status':'rejected','responseAccepted':True,'request':request}),encoding='utf-8');legacy_before=legacy.read_bytes()
            if scenario=='already-pending':current={**old,'status':3}
            client=Mock();client.seller_info.return_value=identity;client.resolve_category.return_value=1
            client.upload_image.side_effect=lambda path,_category:{'imgName':path.name,'imgUrl':newurl}
            client.sku_materials.return_value=[{'skuId':'1','materials':[{**a._binding_material(31,1,newurl,'1'),'status':3}]}]
            model=Mock();model.image_model_stats.return_value={'attempts':{},'usage':{}}
            args=Namespace(output_dir=root,profile='fixture',expected_shop_name='fixture',confirm='AUTO_MAINTAIN',repair_kind=['white'],paid_generation=True,jingmai_first=False,jingmai_ledger=root/'ledger.json',max_model_requests=1,image_prompts_file=promptfile)
            def download(_url,path,*_args):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(oldbytes)
            with patch.object(a,'JdoClient',return_value=client),patch.object(a,'ModelClient',return_value=model),patch.object(a,'_query_binding_materials',return_value={'1':[current]}),patch.object(a,'_download_reference',side_effect=download),patch.object(a,'request_material_image',return_value=newbytes) as call,patch.object(pop_repair,'white_quality_issues',return_value=[]),patch('heideng_merchant.mature_runtime.registered_browser_profile',return_value=None):
                result=pop_repair.run_rejected_repairs(args,a)
            self.assertEqual(oldresponse.read_bytes(),before)
            if legacy:self.assertEqual(legacy.read_bytes(),legacy_before)
            if scenario in ('unknown-old-response','already-pending','reviewed-product-text'):
                call.assert_not_called();client.upload_image.assert_not_called();client.bind_sku_materials.assert_not_called()
                if scenario=='unknown-old-response':self.assertEqual(result['errors'][0]['status'],'unknown')
                if scenario=='reviewed-product-text':self.assertEqual(result['status'],'appeal-only');self.assertTrue(result['manualAppealRequired'])
            else:
                self.assertTrue(call.called,'新提示词未实际进入模型请求：'+str(result));self.assertEqual(call.call_args.args[2],custom)
                self.assertEqual(result['rows'][0]['status'],'pending');self.assertTrue(result.get('imagePromptRevisions'))

if __name__=='__main__':unittest.main()
