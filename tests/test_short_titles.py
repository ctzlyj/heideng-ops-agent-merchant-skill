import importlib,tempfile,unittest,copy,io,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
from heideng_merchant.safety import SafetyError,read_json,atomic_json
from heideng_merchant.operations import digest
from heideng_merchant.shop_material_audit import ShopMaterialAudit
from tests.shop_material_execution_fixtures import Client
from tests.short_title_fixtures import template,NS

class ShortTitlePlansTests(unittest.TestCase):
 def make(self,d):
  cls=importlib.import_module('heideng_merchant.short_titles').ShortTitlePlans
  c=Client(2,1);s=cls(d,c);s.ops.connect('merchant-test','synthetic-store','1')
  c.health=[{'skuId':101,'productId':9,'healthScore':None,'improvementList':[{'improvementDetail':{'troubleCode':'hasShortTitle'}}]},{'skuId':102,'productId':9,'healthScore':100,'improvementList':[{'improvementDetail':{'troubleCode':'hasShortTitle'}}]},{'skuId':1001,'productId':10,'healthScore':99,'improvementList':[]},{'skuId':9001,'productId':9,'healthScore':0,'improvementList':[{'improvementDetail':{'troubleCode':'hasShortTitle'}}]}]
  a=ShopMaterialAudit(d,c).audit('merchant-test');return c,s,a
 def row(self,sku=101,title='轻巧便携收纳商品'):return {'productId':9,'skuId':sku,'shortTitle':title,'review':'passed'}
 def test_whole_scope_not_health_score_subset_and_no_write_success_claim(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);p=s.prepare(a['auditId'],[self.row()]);self.assertEqual(p['onSaleSkuCount'],3);self.assertEqual(p['offSaleSiblingCount'],2);self.assertEqual(p['nativeIssueCount'],2);self.assertEqual(p['reviewedCopyCount'],1);self.assertEqual(p['awaitingCopyCount'],1);self.assertFalse(p['writeExecutionAvailable']);self.assertFalse(p['imported']);self.assertFalse(c.posts)
   rows=s.rows(p['planId'],page_size=1);self.assertEqual(rows['total'],3);self.assertEqual(len(rows['items']),1);self.assertIsNotNone(rows['nextPage'])
 def test_high_scored_issue_is_eligible_and_short_text_has_no_fabricated_minimum16(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);p=s.prepare(a['auditId'],[self.row(102,'便携')]);self.assertEqual(p['reviewedCopyCount'],1);self.assertFalse(c.posts)
 def test_material_failure_does_not_block_known_title_scope(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);c.fault='omitted';a=ShopMaterialAudit(d,c).audit('merchant-test');self.assertFalse(a['materialSourceComplete']);p=s.prepare(a['auditId'],[self.row()]);self.assertEqual(p['onSaleSkuCount'],3)
 def test_foreign_offsale_unknown_and_no_issue_rows_are_not_changed(self):
  for row in (self.row(9001),self.row(1001),{**self.row(),'productId':10},self.row(999)):
   with self.subTest(row=row),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d)
    with self.assertRaises(SafetyError):s.prepare(a['auditId'],[row])
    self.assertFalse(c.posts)
 def test_missing_health_or_mismatched_health_is_unknown_not_empty_title(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);c.health[0]['productId']=99;c.health[1].pop('improvementList');a=ShopMaterialAudit(d,c).audit('merchant-test');p=s.prepare(a['auditId'],[]);self.assertEqual(p['unknownTitleIssueCount'],2);self.assertEqual(p['nativeIssueCount'],0)
   with self.assertRaises(SafetyError):s.prepare(a['auditId'],[self.row()])
 def test_derived_issue_boolean_cannot_override_original_health(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);r=ShopMaterialAudit(d,c).record(a['auditId']);next(row for row in r['scope']['items'] if row['skuId']=='1001')['shortTitleIssue']=True;r['fingerprint']=digest(r['scope']);r['auditId']=r['fingerprint'][:24];atomic_json(ShopMaterialAudit(d,c).path(r['auditId']),r)
   with self.assertRaises(SafetyError):s.prepare(r['auditId'],[])
 def test_catalog_drift_wrong_identity_and_health_not_requested_block(self):
  for fault in ('catalog','identity','health'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d)
    if fault=='catalog':c.products[0]['productName']='changed'
    elif fault=='identity':c.foreign=True
    else:a=ShopMaterialAudit(d,c).audit('merchant-test',include_health=False)
    with self.assertRaises(SafetyError):s.prepare(a['auditId'],[self.row()])
 def test_repeated_intent_same_plan_tamper_and_no_fake_approval(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);p=s.prepare(a['auditId'],[self.row()]);self.assertEqual(s.prepare(a['auditId'],[self.row()])['planId'],p['planId']);path=Path(d)/'short-title-plans'/(p['planId']+'.json');r=read_json(path);r['scope']['changes'][0]['shortTitle']='被改动';atomic_json(path,r)
   with self.assertRaises(SafetyError):s.status(p['planId'])
 def test_unknown_extra_fields_invalid_or_duplicate_copy_are_refused(self):
  for rows in ([{**self.row(),'review':'pending'}],[{**self.row(),'token':'SYNTHETIC'}],[self.row(title='字'*16)],[self.row(),self.row()],[self.row(title='便携'),self.row(102,'便携')]):
   with self.subTest(rows=rows),tempfile.TemporaryDirectory() as d:
    c,s,a=self.make(d)
    with self.assertRaises(SafetyError):s.prepare(a['auditId'],rows)
 def test_safe_workbooks_are_intermediate_not_import_or_official_origin(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);p=s.prepare(a['auditId'],[self.row()]);t=Path(d)/'user-template.xlsx';t.write_bytes(template());w=s.compile(p['planId'],t);self.assertEqual(w['workbookCount'],1);self.assertFalse(w['imported']);self.assertFalse(w['templateOriginVerified']);self.assertFalse(w['readyForImport']);self.assertFalse(c.posts);self.assertEqual(s.compile(p['planId'],t)['artifacts'],w['artifacts'])
 def test_empty_inventory_has_complete_no_work_not_fake_import(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d)
   for product in c.products:product['productStatus']=104
   a=ShopMaterialAudit(d,c).audit('merchant-test');p=s.prepare(a['auditId'],[]);self.assertEqual(p['onSaleSkuCount'],0);self.assertTrue(p['noCopyWork']);self.assertFalse(p['imported'])

 def test_complete_5001_sku_scope_is_5000_plus1_not_truncated(self):
  from tests.test_shop_material_audit import ShopClient
  cls=importlib.import_module('heideng_merchant.short_titles').ShortTitlePlans
  with tempfile.TemporaryDirectory() as d:
   c=ShopClient(large=5001);c.health=[{'skuId':row['skuId'],'productId':row['productId'],'healthScore':100,'improvementList':[{'improvementDetail':{'troubleCode':'hasShortTitle'}}]} for row in c.skus if row['status']==103];c.fault='omitted';s=cls(d,c);s.ops.connect('merchant-test','synthetic-store','1');a=ShopMaterialAudit(d,c).audit('merchant-test');rows=[{'productId':row['productId'],'skuId':row['skuId'],'shortTitle':'简约收纳商品'+str(row['skuId']),'review':'passed'} for row in c.skus if row['status']==103];plan=s.prepare(a['auditId'],rows)
   self.assertEqual(plan['onSaleSkuCount'],5001);self.assertEqual(plan['reviewedCopyCount'],5001);self.assertEqual(plan['batchCount'],2);batches=s.rows(plan['planId'],view='chunks')['items'];self.assertEqual([b['rowCount'] for b in batches],[5000,1]);self.assertFalse(c.posts)

 def test_excluded_offsale_siblings_have_bounded_dedicated_view(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);p=s.prepare(a['auditId'],[]);all_rows=s.rows(p['planId'],view='siblings',page_size=200);self.assertEqual(all_rows['total'],5);self.assertEqual(sum(r['state']=='excluded-offsale' for r in all_rows['items']),2);self.assertFalse(c.posts)
 def test_valid_other_plan_file_cannot_be_used_under_requested_id(self):
  with tempfile.TemporaryDirectory() as d:
   c,s,a=self.make(d);p=s.prepare(a['auditId'],[self.row()]);other=s.prepare(a['auditId'],[self.row(102,'可靠收纳商品')]);src=Path(d)/'short-title-plans'/(other['planId']+'.json');dst=Path(d)/'short-title-plans'/(p['planId']+'.json');dst.write_bytes(src.read_bytes())
   with self.assertRaises(SafetyError):s.status(p['planId'])

class ShortTitleWorkbookTests(unittest.TestCase):
 def compile(self,rows,raw=None):return importlib.import_module('heideng_merchant.short_title_workbook').compile_template(raw or template(),rows)
 def test_header_format_retained_examples_removed_and_big_sku_is_text(self):
  rows=[{'skuId':'9007199254740993','shortTitle':'便携'}];raw=self.compile(rows)
  with zipfile.ZipFile(io.BytesIO(raw)) as z:
   sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'));ns={'s':NS};cell=sheet.find("s:sheetData/s:row[@r='3']/s:c[@r='A3']",ns);self.assertEqual(cell.attrib['t'],'inlineStr');self.assertEqual(''.join(cell.itertext()),'9007199254740993');self.assertIsNotNone(sheet.find('s:cols',ns));self.assertNotIn(b'SYNTHETIC-EXAMPLE',z.read('xl/sharedStrings.xml'));self.assertEqual(z.read('docProps/core.xml'),zipfile.ZipFile(io.BytesIO(template())).read('docProps/core.xml'))
 def test_template_macros_external_relations_entities_formula_and_multiple_sheet_refused(self):
  sheet=zipfile.ZipFile(io.BytesIO(template())).read('xl/worksheets/sheet1.xml').decode()
  for extra in ({'xl/vbaProject.bin':'synthetic'},{'xl/worksheets/_rels/sheet1.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" TargetMode="External" Target="https://example.com/"/></Relationships>'},{'xl/worksheets/sheet1.xml':sheet.replace('<worksheet','<!DOCTYPE x [<!ENTITY y "injected">]><worksheet')},{'xl/worksheets/sheet1.xml':sheet.replace('<v>0</v>','<f>1+1</f><v>0</v>')},{'xl/worksheets/sheet2.xml':sheet},{'../outside.xml':'x'}):
   with self.subTest(extra=list(extra)):
    with self.assertRaises(SafetyError):self.compile([{'skuId':'101','shortTitle':'便携'}],template(extra))
 def test_wrong_headers_zip_duplicates_invalid_text_and_too_many_rows_refused(self):
  bad=template({'xl/sharedStrings.xml':f'<sst xmlns="{NS}"><si><t>商品编号</t></si><si><t>短标题</t></si></sst>'})
  with self.assertRaises(SafetyError):self.compile([{'skuId':'101','shortTitle':'便携'}],bad)
  out=io.BytesIO(template())
  with zipfile.ZipFile(out,'a') as z:z.writestr('xl/workbook.xml','duplicate')
  for raw in (out.getvalue(),b'not-a-zip'):
   with self.assertRaises(SafetyError):self.compile([{'skuId':'101','shortTitle':'便携'}],raw)
  for rows in ([{'skuId':'101','shortTitle':''}],[{'skuId':'101','shortTitle':'字'*16}],[{'skuId':True,'shortTitle':'便携'}],[{'skuId':'1','shortTitle':'便携'}]*5001):
   with self.assertRaises(SafetyError):self.compile(rows)
 def test_template_and_outputs_deterministic_and_literal_formula_text_not_formula(self):
  rows=[{'skuId':'101','shortTitle':'=杯子'}];a=self.compile(rows);self.assertEqual(self.compile(rows),a)
  with zipfile.ZipFile(io.BytesIO(a)) as z:self.assertNotIn(b'<f>',z.read('xl/worksheets/sheet1.xml'));self.assertIn('=杯子'.encode(),z.read('xl/worksheets/sheet1.xml'))

 def test_native_template_empty_directory_records_are_preserved(self):
  raw=self.compile([{'skuId':'101','shortTitle':'便携'}],template({'_rels/':'','xl/':'','xl/_rels/':''}))
  with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertIn('_rels/',z.namelist());self.assertEqual(z.read('_rels/'),b'')


 def test_workbook_declared_relationship_graph_must_bind_exact_single_sheet(self):
  original=zipfile.ZipFile(io.BytesIO(template())).read('xl/_rels/workbook.xml.rels').decode();book=zipfile.ZipFile(io.BytesIO(template())).read('xl/workbook.xml').decode()
  for extra in ({'xl/_rels/workbook.xml.rels':original.replace('worksheets/sheet1.xml','worksheets/ghost.xml')},{'xl/workbook.xml':book.replace('</sheets>','<sheet name="extra" sheetId="2" r:id="rId1"/></sheets>')},{'[Content_Types].xml':zipfile.ZipFile(io.BytesIO(template())).read('[Content_Types].xml').decode().replace('spreadsheetml.sheet.main+xml','spreadsheetml.worksheet+xml')}):
   with self.subTest(extra=list(extra)):
    with self.assertRaises(SafetyError):self.compile([{'skuId':'101','shortTitle':'便携'}],template(extra))
 def test_active_external_data_connections_are_not_preserved(self):
  extra={'xl/connections.xml':'<connections xmlns="'+NS+'"><connection id="1" refreshOnLoad="1"><webPr url="https://example.com/external"/></connection></connections>'}
  with self.assertRaises(SafetyError):self.compile([{'skuId':'101','shortTitle':'便携'}],template(extra))
 def test_shared_string_compatibility_namespace_remains_declared(self):
  original=zipfile.ZipFile(io.BytesIO(template())).read('xl/sharedStrings.xml').decode();original=original.replace('<sst ','<sst xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" mc:Ignorable="x14ac" ');result=self.compile([{'skuId':'101','shortTitle':'便携'}],template({'xl/sharedStrings.xml':original}))
  with zipfile.ZipFile(io.BytesIO(result)) as z:
   raw=z.read('xl/sharedStrings.xml');mapping={p:u for event,(p,u) in ET.iterparse(io.BytesIO(raw),events=('start-ns',))};self.assertIn('x14ac',mapping);self.assertNotIn(b'SYNTHETIC-EXAMPLE',raw)


 def test_known_part_names_do_not_allow_wrong_root_or_hidden_external_data(self):
  with self.assertRaises(SafetyError):self.compile([{'skuId':'101','shortTitle':'便携'}],template({'xl/sharedStrings.xml':f'<notSst xmlns="{NS}"><si><t>SKUID</t></si><si><t>短标题</t></si></notSst>'}))
  sheet=zipfile.ZipFile(io.BytesIO(template())).read('xl/worksheets/sheet1.xml').decode();bad=sheet.replace('</worksheet>','<extLst><ext><webPr url="https://example.com/external"/></ext></extLst></worksheet>')
  with self.assertRaises(SafetyError):self.compile([{'skuId':'101','shortTitle':'便携'}],template({'xl/worksheets/sheet1.xml':bad}))

if __name__=='__main__':unittest.main()
