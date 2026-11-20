"""Frozen task handoff tests exercise real plan validation, never shop calls."""
import json,os,tempfile,unittest
from argparse import Namespace
from unittest.mock import Mock,patch
from pathlib import Path
import tests.test_mature_materials as helpers

class AuditHandoffTests(unittest.TestCase):
    setUp=helpers.MatureMaterialsTests.setUp
    tearDown=helpers.MatureMaterialsTests.tearDown
    agent=helpers.MatureMaterialsTests.agent
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
