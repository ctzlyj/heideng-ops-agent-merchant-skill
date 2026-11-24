"""Local, visible-form evidence for freight templates; no browser session or platform writes."""
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from scripts.freight_page_draft import make_draft, verify_form, main


def example():
    def rule(method, fee):
        return {'paymentMethod':method,'regions':['皖','苏'],'firstQuantity':1,'firstFee':fee,
                'nextQuantity':'0.5','nextFee':'2','special':'保留源区域条件'}
    source={'shop':{'profile':'demo-a','shopId':'11','venderId':'31'},
            'freightTemplates':[{'id':'47','complete':True,'receipt':'local/source-details.json',
              'rules':{'payer':'buyer','chargeBy':'weight','unit':'kg','currency':'CNY',
                       'zones':[rule('在线支付','8'),rule('货到付款','12')]}}]}
    target={'shop':{'profile':'demo-b','shopId':'12','venderId':'32'}}
    return {'source':source,'target':target}


def observed(draft):
    rows=[]
    for i,r in enumerate(draft['ruleTable']):
        rows.append({'rowKey':r['rowKey'],'paymentMethod':r['paymentMethod'],'rowRef':f'本次页面-规则{i+1}',
                     'rowRegions':r['regions'],'fields':deepcopy(r['fields']),
                     'regionPicker':{'receipt':f'本次页面-地区{i+1}','complete':True,
                                     'controls':[{'role':'checkbox','region':v,'checked':True} for v in r['regions']]}})
    return {'stage':'editing','shop':draft['targetShop'],'draftFingerprint':draft['draftFingerprint'],
            'receipt':'local/target-form.json','allRowsVisible':True,
            'globalFields':deepcopy(draft['globalFields']),'rows':rows}


class FreightPageDraftTests(unittest.TestCase):
    def test_separate_payment_rows_publish_no_template_and_reopen_requires_a_real_id(self):
        draft=make_draft(example(),'47')
        self.assertEqual([(r['支付方式'],r['首费']) for r in draft['创建规则表']],[('在线支付','8'),('货到付款','12')])
        page=observed(draft)
        checked=verify_form(draft,page)
        self.assertEqual((checked['status'],checked['savedTemplateVerified'],checked['platformWrites']),('form-matches',False,0))
        page['stage']='reopened-detail'
        with self.assertRaisesRegex(ValueError,'官方模板 ID'):
            verify_form(draft,page)
        page['templateId']='82'
        self.assertEqual(verify_form(draft,page)['targetTemplateId'],'82')

    def test_expanded_text_mixed_parent_or_checkbox_outside_row_cannot_satisfy_selection(self):
        draft=make_draft(example(),'47')
        page=observed(draft)
        row=page['rows'][0]
        for state in ({'role':'treeitem','expanded':True,'region':'苏'},
                      {'role':'checkbox','checked':'mixed','region':'苏'},
                      {'role':'checkbox','checked':False,'region':'苏'}):
            row['regionPicker']['controls']=[state,{'role':'checkbox','checked':True,'region':'皖'}]
            self.assertEqual(verify_form(draft,page)['status'],'form-differences')
        page=observed(draft)
        page['rows'][0]['rowRegions']=['全国']
        self.assertEqual(verify_form(draft,page)['status'],'form-differences')

    def test_payment_misassignment_fee_mismatch_or_extra_rule_cannot_pass(self):
        draft=make_draft(example(),'47')
        for case in ('wrong-payment','wrong-next-fee','extra'):
            with self.subTest(case=case):
                page=observed(draft)
                if case=='wrong-payment':page['rows'][1]['paymentMethod']='在线支付'
                if case=='wrong-next-fee':page['rows'][1]['fields']['nextFee']='0'
                if case=='extra':page['rows'].append(deepcopy(page['rows'][0]))
                self.assertEqual(verify_form(draft,page)['status'],'form-differences')
        page=observed(draft)
        page['rows'][0]['fields']['firstFee']='8.00'
        self.assertEqual(verify_form(draft,page)['status'],'form-matches')

    def test_unknown_payment_section_and_another_shop_or_source_fingerprint_are_not_inferred(self):
        evidence=example()
        del evidence['source']['freightTemplates'][0]['rules']['zones'][0]['paymentMethod']
        plan=make_draft(evidence,'47')
        self.assertEqual(plan['status'],'needs-source-evidence')
        self.assertIsNone(plan['创建规则表'][0]['支付方式'])
        valid=make_draft(example(),'47')
        page=observed(valid)
        for wrong in ({'shop':valid['sourceShop']},{'draftFingerprint':'another'}):
            with self.assertRaisesRegex(ValueError,'目标店或创建规则表'):
                verify_form(valid,{**page,**wrong})

    def test_local_cli_emits_json_and_preserves_original_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            src=root/'source.json'
            src.write_text(json.dumps(example()),encoding='utf-8')
            before=src.read_bytes()
            output=root/'draft.json'
            args=['--evidence',str(src),'--source-template','47','--output',str(output)]
            with redirect_stdout(StringIO()):
                self.assertEqual(main(args),0)
                self.assertEqual(main(args[:-1]+[str(src)]),2)
            self.assertEqual(json.loads(output.read_bytes())['platformWrites'],0)
            self.assertEqual(src.read_bytes(),before)
