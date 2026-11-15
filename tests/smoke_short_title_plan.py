"""Fresh installation, exact CLI/modules, synthetic complete short-title planning."""
import json,sys,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from heideng_merchant.safety import file_sha,clean_environment,atomic_json
CHILD=r'''import sys,copy,socket,json,zipfile,io,xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
installed,source,home=map(Path,sys.argv[1:4]);sys.path[:0]=[str(installed),str(source)]
from heideng_merchant import cli,short_titles,short_title_contract,short_title_workbook
from heideng_merchant.safety import atomic_json
from tests.shop_material_execution_fixtures import Client
from tests.short_title_fixtures import template,NS
assert all(Path(m.__file__).resolve().is_relative_to(installed.resolve()) for m in (cli,short_titles,short_title_contract,short_title_workbook))
socket.socket.connect=lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('synthetic-only'))
socket.create_connection=lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('synthetic-only'))
c=Client(2,1);c.health=[{'skuId':101,'productId':9,'healthScore':None,'improvementList':[{'improvementDetail':{'troubleCode':'hasShortTitle'}}]},{'skuId':102,'productId':9,'healthScore':100,'improvementList':[{'improvementDetail':{'troubleCode':'hasShortTitle'}}]},{'skuId':1001,'productId':10,'healthScore':99,'improvementList':[]}]
def command(name,*args):return cli.run(cli.parser().parse_args(['--home',str(home),name,*map(str,args)]))
with patch('heideng_merchant.cli.OfficialClient',return_value=c):
 command('shop-connect','--profile','merchant-test','--shop-name','synthetic-store','--vender-id','1');audit=command('sku-material-shop-audit','--profile','merchant-test');recipe=home/'reviewed.json';atomic_json(recipe,[{'productId':9,'skuId':101,'shortTitle':'便携','review':'passed'}]);p=command('short-title-plan','--audit-id',audit['auditId'],'--changes',recipe)
 assert p['onSaleSkuCount']==3 and p['offSaleSiblingCount']==2 and p['nativeIssueCount']==2 and p['awaitingCopyCount']==1 and p['reviewedCopyCount']==1 and not p['writeExecutionAvailable'] and not p['imported']
 assert command('short-title-status','--plan-id',p['planId'])['fingerprint']==p['fingerprint'];page=command('short-title-rows','--plan-id',p['planId'],'--page-size',1);assert page['total']==3 and page['nextPage']==2
 siblings=command('short-title-rows','--plan-id',p['planId'],'--view','siblings','--page-size',200);assert siblings['total']==5 and sum(row['state']=='excluded-offsale' for row in siblings['items'])==2
 file=home/'synthetic-template.xlsx';file.write_bytes(template());w=command('short-title-workbooks','--plan-id',p['planId'],'--template',file);assert w['workbookCount']==1 and not w['templateOriginVerified'] and not w['readyForImport'] and not w['imported'] and not w['merchantManualUploadRequested']
 artifact=home/'.heideng-merchant'/w['artifacts'][0]['localPath']
 with zipfile.ZipFile(artifact) as z:
  root=ET.fromstring(z.read('xl/worksheets/sheet1.xml'));cell=root.find("{*}sheetData/{*}row[@r='3']/{*}c[@r='A3']");assert cell.attrib['t']=='inlineStr' and ''.join(cell.itertext())=='101';assert b'SYNTHETIC-EXAMPLE' not in z.read('xl/sharedStrings.xml')
 assert not c.posts and not (home/'.heideng-merchant/tasks').exists()
 try:cli.parser().parse_args(['short-title-execute','--plan-id',p['planId']])
 except SystemExit as error:assert error.code==2
 else:raise AssertionError('unimplemented import advertised as executable')
 print(json.dumps({'status':'passed','installedPathsAsserted':True,'onSaleSkuCount':3,'offSaleSiblingCount':2,'nativeIssues':2,'reviewedCopies':1,'remainingCopies':1,'workbookRows':1,'templateOriginVerified':False,'writeExecutionAvailable':False,'merchantApi':'synthetic','paidModels':0}))
'''
def main():
 archive=ROOT/'dist/heideng-ops-agent-merchant-0.1.0.zip';sha=file_sha(archive);base=ROOT/'.agent-work/short-title-plan-audit';base.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='ht-') as d:
  home=Path(d);env=clean_environment(home);child=home/'installed.py';child.write_text(CHILD,encoding='utf-8')
  for stage,args in [('install',[sys.executable,'-I','-X','utf8','-B',ROOT/'install.py','--offline','--home',home,'--archive',archive,'--sha256',sha]),('chain',[sys.executable,'-I','-X','utf8','-B',child,home/'.codex/skills/heideng-ops-agent-merchant',ROOT,home])]:
   r=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,timeout=180);(base/(stage+'.log')).write_bytes(r.stdout+r.stderr);assert r.returncode==0,'short-title installed smoke failed: '+stage
   if stage=='chain':result=json.loads(r.stdout)
 assert file_sha(archive)==sha;record={'status':'passed','archiveSha256':sha,'freshHomeInstall':True,'sourceAndMerchantCalls':'synthetic','template':'synthetic-not-internal-asset','planningOnly':True,'result':result,'goalComplete':False};atomic_json(base/'installed-short-title-plan-smoke.json',record);print(json.dumps(record))
if __name__=='__main__':main()
