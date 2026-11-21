"""Frozen task handoff tests exercise real plan validation, never shop calls."""
from tests.fee_consent import isolated_fees, signed_fixture
import json,os,tempfile,unittest
from argparse import Namespace
from unittest.mock import Mock,patch
from pathlib import Path
import tests.test_mature_materials as helpers

@isolated_fees
def run_approved_repair(args, agent):
    import pop_repair
    result = pop_repair.run_rejected_repairs(args, agent)
    if result['status'] != 'fee-approval-required':
        return result
    quote = result['feeQuote']
    args.fee_approval_file = Path(args.output_dir) / 'fixture-fee.json'
    args.fee_approval_file.write_text(json.dumps(signed_fixture({**quote, 'billing':'requests',
        'maxRequests':1, 'approvalRef':'synthetic-merchant-message'})), encoding='utf-8')
    return pop_repair.run_rejected_repairs(args, agent)


class AuditHandoffTests(unittest.TestCase):
    setUp=helpers.MatureMaterialsTests.setUp
    tearDown=helpers.MatureMaterialsTests.tearDown
    agent=helpers.MatureMaterialsTests.agent
    def test_sibling_images_only_feed_real_missing_slots_to_binding(self):
        a = self.agent()
        rows = [dict(skuId=str(n), productId='11') for n in (1, 2, 3)]
        def material(sku, state):
            return dict(a._binding_material(32, 1, f'https://img10.360buyimg.com/imgzone/jfs/{sku}.jpg',sku), status=state)
        snapshot = {'1':[material('1',4)], '2':[material('2',3)], '3':[]}
        state_counts = {state:set() for state in ('approved','pending','rejected','missing','unknown')}
        state_counts['slotCounts'] = dict.fromkeys(state_counts,0)
        with patch.object(a,'_query_binding_materials',return_value=snapshot):
            missing, _ = a.inspect_unscored_materials(None,rows,state_counts)
            self.assertIn('scene1',missing['11'])
            self.assertEqual(state_counts['pending'],{'2'})
            # Different approved values on both siblings with no empty slot do not need repair.
            snapshot['2']=[material('2',4)]
            healthy,_ = a.inspect_unscored_materials(None,rows[:2])
            self.assertNotIn('scene1',healthy['11'])
            snapshot['2']=[material('2',3)]
            sku_ids=('1','2','3')
            job=a.SpuJob('11','1','fixture',sku_ids,tuple((k,'fixture') for k in sku_ids),
                         needs_white=False,needs_transparent=False,needs_selling_points=False,
                         needs_selling_image=False,needs_scenes=True,scene_orders=(1,))
            prepared=a.PreparedSource('jdo-pop','fixture',(),tuple(a.SourceRow(k,'fixture','11') for k in sku_ids),
                                      (job,),3,0,0)
            with tempfile.TemporaryDirectory() as d:
                directory=Path(d)
                sp=directory/'.state/task.json'; data={'jobs':{}};a._bind_state(data,prepared,sp)
                data['jobs']['11']['uploaded_urls']={'scene1':'https://img10.360buyimg.com/imgzone/jfs/new.jpg'}
                a._save_state(sp,data)
                plan=a.prepare_material_binding_plan(Mock(),prepared,directory)
                self.assertFalse(plan.preflight_failures)
                self.assertEqual(len(plan.requests),1)
                self.assertEqual(plan.requests[0]['skuIds'],['3'])
                self.assertEqual([r['skuId'] for r in plan.requests[0]['body']['skuMaterials']],[3])

    def test_legacy_repair_discovery_and_read_only_recovery(self):
        from heideng_merchant.merchant_tasks import task_context
        a=self.agent()
        import pop_repair
        with tempfile.TemporaryDirectory() as d:
            state=Path(d); out=state/'work/materials/repair';out.mkdir(parents=True)
            identity={'shopId':'9','venderId':'10','shopName':'fixture'}
            a._save_state(out/'repair-scope.json',{'shopIdentity':identity,'originals':{'1':[]}})
            a._save_state(out/'.state/merchant-result-repair-rejected.json',
                          {'shopName':'fixture','rows':[{'skuId':'1','status':'pending'}],'modelStats':{'attempts':{'fixture':1}}})
            self.assertEqual(task_context(state,'9','10')['tasks'][0]['results']['repair-rejected']['modelAttempts'],1)
            self.assertEqual(task_context(state,'9','9')['tasks'],[])
            m=a._binding_material(33,1,'https://img10.360buyimg.com/imgzone/jfs/new.jpg','1')
            request={'skuIds':['1'],'materialType':33,'body':{'skuMaterials':[{'skuId':1,'materials':[m]}]}}
            a._save_state(out/'shared-bindings/x.json',{'request':request,'status':'unknown'})
            client=Mock();client.seller_info.return_value=identity
            with patch.object(a,'_query_binding_materials',return_value={'1':[{**m,'status':4}]}):
                result=pop_repair.read_repair_status(client,out,a)
            self.assertEqual(result['rows'][0]['status'],'approved')
            self.assertFalse(result['writesPerformed']);client.bind_sku_materials.assert_not_called()
            a._save_state(out/'shared/ref/white.request.json',{'status':'intent'})
            with patch.object(a,'_query_binding_materials',return_value={'1':[]}):
                self.assertEqual(pop_repair.read_repair_status(client,out,a)['status'],'unknown')
            self.assertEqual(task_context(state,'9','10')['tasks'][0]['results']['check-repair-status']['phase'],'needs-reconciliation')

    def test_old_false_plan_checked_before_fee_or_generation(self):
        a=self.agent()
        ids=('1','2')
        job=a.SpuJob('11','1','fixture',ids,tuple((sku,'fixture') for sku in ids))
        rows=tuple(a.SourceRow(sku,'fixture','11','100',('信息分90+-素材直查缺失',)) for sku in ids)
        prepared=a.PreparedSource('jdo-pop','fixture',(),rows,(job,),2,0,0)
        seller={'shopName':'fixture','shopId':'9','venderId':'10'}
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            source=out/'original.xlsx';source.write_bytes(b'original')
            a.write_pop_auto_maintain_plan(prepared,{}, {}, seller,out,source,target_spu_id=None)
            frozen=out/a.AUTO_MAINTAIN_PLAN_NAME;before=frozen.read_bytes()
            client=Mock();client.seller_info.return_value=seller
            snapshot={k:[dict(a._binding_material(31,1,f'https://img10.360buyimg.com/imgzone/jfs/{k}.jpg',k),status=4)] for k in ids}
            args=Namespace(confirm='AUTO_MAINTAIN',profile='fixture',expected_shop_name='fixture',output_dir=out,business_mode='pop')
            with patch.object(a,'JdoClient',return_value=client),patch.object(a,'_query_binding_materials',return_value=snapshot),patch.object(a,'ModelClient') as model:
                self.assertEqual(a.run_generate_auto_maintain(args)['status'],'plan-superseded')
                self.assertEqual(a.run_auto_maintain(args)['paidRequestCount'],0)
                self.assertEqual(before,frozen.read_bytes());model.assert_not_called()
        self.assertFalse(client.bind_sku_materials.called)

    def test_paid_decision_does_not_hold_free_work(self):
        from threading import Event
        a=self.agent()
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':d}):
            out=Path(d);prepared,seller=self.fixture(a,out)
            client=Mock();client.seller_info.return_value=seller
            args=Namespace(output_dir=out,profile='fixture',expected_shop_name=seller['shopName'],
                           agent_text_file=out/'text.json',confirm='AUTO_MAINTAIN',target_spu_id=None)
            entered=Event();submitted=Event()
            def attrs(*args):
                entered.set()
                if not submitted.wait(2):raise AssertionError('free title lane blocked by independent API work')
                return {'planned':1}
            def title(*args):
                self.assertTrue(entered.wait(2));submitted.set()
                return {'status':'verified','rowCount':2,'shortTitleFiles':[]}
            with patch.object(a,'run_maintenance_attributes',side_effect=attrs),patch.object(a,'run_title_work_item',side_effect=title),patch.object(a,'ModelClient') as paid:
                result=a.free_work_while_awaiting_fee(args,prepared,seller,client,[],{'status':'fee-approval-required'})
                self.assertEqual(result['shortTitleDelivery']['rowCount'],2);paid.assert_not_called()
                self.assertTrue((out/'.state/merchant-result-maintain-short-titles.json').is_file())

    def fixture(self,a,root):
        rows=tuple(a.SourceRow(sku,'fixture',spu) for sku,spu in [('1','11'),('2','22')])
        jobs=tuple(a.SpuJob(spu,sku,'fixture',(sku,),((sku,'fixture'),),(sku,)) for sku,spu in [('1','11'),('2','22')])
        prepared=a.PreparedSource('fixture','Sheet1',('SKUID','商品名称','SPUID'),rows,jobs,2,2,0)
        seller={'shopName':'fixture-shop','venderId':'123','shopId':'123'}
        source=a._write_jdo_source(prepared,root/'source.xlsx')
        a.write_pop_auto_maintain_plan(prepared,{}, {},seller,root,source,target_spu_id=None)
        return prepared,seller
    def test_verified_full_task_text_projects_to_subset_without_rewriting_input(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);full,seller=self.fixture(a,root);selected,_,_,_=a.load_pop_auto_maintain_plan(root,seller,'11')
            path=root/'host-text.json';path.write_text(json.dumps({'sellingPoints':{},'shortTitles':{'1':'保暖纯棉圆领长袖上衣','2':'舒适宽松圆领长袖上衣'}},ensure_ascii=False),encoding='utf-8')
            before=path.read_bytes()
            result=a.load_scoped_agent_text(path,selected,root,seller)
            self.assertEqual(result['short_titles'],{'1':'保暖纯棉圆领长袖上衣'});self.assertEqual(path.read_bytes(),before)
    def test_external_full_text_is_not_silently_filtered_and_wrong_shop_is_rejected(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'task';root.mkdir();full,seller=self.fixture(a,root);selected,_,_,_=a.load_pop_auto_maintain_plan(root,seller,'11')
            path=Path(d)/'external.json';path.write_text(json.dumps({'shortTitles':{'1':'保暖纯棉圆领长袖上衣','2':'舒适宽松圆领长袖上衣'}}),encoding='utf-8')
            with self.assertRaises(ValueError):a.load_scoped_agent_text(path,selected,root,seller)
            path=root/'host-text.json';path.write_text(json.dumps({'shortTitles':{'1':'保暖纯棉圆领长袖上衣','9':'舒适宽松圆领长袖上衣'}}),encoding='utf-8')
            with self.assertRaises(ValueError):a.load_scoped_agent_text(path,selected,root,seller)
            with self.assertRaises(ValueError):a.load_scoped_agent_text(path,selected,root,{**seller,'venderId':'999'})
    def test_subset_resume_keeps_original_batch_state_and_sibling_receipt(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);full,seller=self.fixture(a,root);state_path=root/'批次001/.state/task.json'
            state={'jobs':{}}
            a._bind_state(state,full,state_path)
            state['jobs']['22']['uploaded_urls']={'white':'https://img14.360buyimg.com/imgzone/fixture.jpg'}
            signature=state['task_signature'];sibling=json.loads(json.dumps(state['jobs']['22']))
            selected,_,_,_=a.load_pop_auto_maintain_plan(root,seller,'11')
            a._bind_state(state,selected,state_path)
            self.assertEqual(state['task_signature'],signature);self.assertEqual(state['jobs']['22'],sibling)
    def test_plan_handoff_names_exact_host_inputs_scope_and_resume_commands(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);full,seller=self.fixture(a,root)
            result=a.host_task_handoff(full,root,seller,'fixture-profile')
        self.assertEqual(result['scope']['spuIds'],['11','22'])
        self.assertEqual(result['textInput']['neededShortTitleSkuIds'],['1','2'])
        self.assertIn('sellingPoints',result['textInput']['schema']['properties'])
        self.assertIn('--agent-text-file',result['executeArgv'])
        self.assertIn('reconcile-receipts',result['recoverArgv'])
        self.assertIn('plan-missing-attrs',result['attributes']['inventoryArgv'])

    def test_attribute_handoff_exposes_actual_evidence_and_option_index_format(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);full,seller=self.fixture(a,root);result=a.host_task_handoff(full,root,seller,'fixture-profile')
        fields=result['attributes'].get('schema',{}).get('additionalProperties',{}).get('properties',{})
        self.assertIn('evidence',fields);self.assertIn('choices',fields)
        choice=fields['choices']['items']['properties']
        self.assertIn('n',choice);self.assertEqual(choice['confidence']['const'],'high')
        self.assertIn('complete-product-attrs',result['attributes']['applyArgv'])
        self.assertIn('--product-id',result['attributes']['applyArgv'])

    def test_original_plan_entry_persists_handoff_with_parseable_mature_commands(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);full,seller=self.fixture(a,root)
            client=Mock();client.seller_info.return_value=seller
            args=Namespace(output_dir=root,business_mode='pop',profile='fixture-profile',expected_shop_name='fixture-shop',target_spu_id='11',refresh=False,include_full_score=False)
            state=root/'isolated merchant'
            with patch.dict(os.environ,{'HEIDENG_MERCHANT_HOME':str(state)}),patch.object(a,'JdoClient',return_value=client):result=a.run_plan_auto_maintain(args)
            handoff=json.loads(Path(result['hostHandoff']['file']).read_text(encoding='utf-8'))
            self.assertEqual(handoff['scope']['spuIds'],['11']);self.assertFalse(handoff['executionAuthorized'])
            argv=handoff['executeArgv']
            self.assertEqual(argv[argv.index('--state')+1],str(state))
            self.assertEqual(a.build_parser().parse_args(argv[argv.index('--')+1:]).target_spu_id,'11')
            for key in ('inventoryArgv','replanArgv','applyArgv'):
                argv=handoff['attributes'][key]
                parsed=a.build_parser().parse_args(argv[argv.index('--')+1:])
                self.assertEqual(parsed.product_id,['11'])
            from heideng_merchant.merchant_tasks import task_context
            self.assertEqual(len(task_context(state,'123','123')['tasks']),1)
            self.assertEqual(task_context(state,'123','999')['tasks'],[])

    def test_free_title_work_item_uses_own_receipt_directory(self):
        a=self.agent()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,seller=self.fixture(a,root)
            path=root/'host-text.json'
            path.write_text(json.dumps({'shortTitles':{'1':'保暖纯棉圆领长袖上衣','2':'舒适宽松圆领长袖上衣'}}),encoding='utf-8')
            client=Mock();client.seller_info.return_value=seller
            args=Namespace(output_dir=root,profile='fixture',expected_shop_name=seller['shopName'],
                           agent_text_file=path,target_spu_id=None,confirm='AUTO_MAINTAIN')
            with patch.object(a,'JdoClient',return_value=client),patch(
                'pop_workflow.complete_short_title_import',return_value={'status':'verified'}) as submit,patch.object(a,'ModelClient') as paid:
                self.assertEqual(a.run_title_work_item(args)['status'],'verified')
            self.assertEqual(submit.call_args.args[1]['rowCount'],2)
            paid.assert_not_called()
            self.assertTrue((root/'短标题独立交付'/'全店'/'短标题导入.xlsx').exists())

if __name__=='__main__':unittest.main()
