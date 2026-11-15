"""Read-only short-title plans and intermediate workbooks; not an import executor."""
import re,hashlib
from pathlib import Path
from . import VERSION
from .operations import Operations,digest
from .safety import SafetyError,safe_join,read_json,file_sha
from .state import FileLock
from .video_delivery import _once
from .short_title_contract import source_context,changes_checked,chunks
from .shop_material_execution_contract import current_catalog

class ShortTitlePlans:
 def __init__(self,state,client):self.state=Path(state).resolve();self.client=client;self.ops=Operations(self.state,client)
 def _path(self,ident):
  if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{24}',ident):raise SafetyError('short-title-plan-id-required')
  return safe_join(self.state,'short-title-plans/'+ident+'.json')
 def plan(self,plan_id):
  p=read_json(self._path(plan_id))
  if not isinstance(p,dict) or set(p)!={'planId','fingerprint','scope'} or not isinstance(p['scope'],dict) or p['fingerprint']!=digest(p['scope']) or p['planId']!=p['fingerprint'][:24] or p['planId']!=plan_id:raise SafetyError('original-short-title-plan-changed')
  scope=p['scope']
  if set(scope)!={'kind','runtimeVersion','auditId','auditFingerprint','shop','changes','chunks'} or scope['kind']!='native-short-title-copy-plan':raise SafetyError('complete-short-title-copy-plan-required')
  record,coverage=source_context(self.state,scope['auditId'],scope['auditFingerprint']);raw=[{k:r[k] for k in ('productId','skuId','shortTitle','review')} for r in scope['changes']]
  if scope['shop']!=record['scope']['shop'] or scope['changes']!=changes_checked(coverage,raw) or scope['chunks']!=chunks(scope['changes']):raise SafetyError('original-short-title-copy-scope-changed')
  return p
 def prepare(self,audit_id,changes):
  with FileLock(self.state/'short-title-plan.lock'):
   record,coverage=source_context(self.state,audit_id);ready=changes_checked(coverage,changes);current_catalog(self.ops,record,all_siblings=True);scope={'kind':'native-short-title-copy-plan','runtimeVersion':VERSION,'auditId':audit_id,'auditFingerprint':record['fingerprint'],'shop':record['scope']['shop'],'changes':ready,'chunks':chunks(ready)};fp=digest(scope);p={'planId':fp[:24],'fingerprint':fp,'scope':scope};path=self._path(p['planId'])
   if path.exists():self.plan(p['planId'])
   else:_once(path,p)
   return self.status(p['planId'])
 def coverage(self,plan,*,include_offsale=False):
  scope=plan['scope'];_,rows=source_context(self.state,scope['auditId'],scope['auditFingerprint']);ready={row['skuId']:row for row in scope['changes']};out=[]
  for row in rows:
   if row['onSale'] is not True and not include_offsale:continue
   state='excluded-offsale' if row['onSale'] is not True else 'reviewed-copy' if row['skuId'] in ready else 'awaiting-copy' if row['nativeTitleIssue'] is True else 'unknown-title-issue' if row['nativeTitleIssue'] is None else 'native-no-title-issue'
   out.append({**row,'state':state,'proposedShortTitle':ready.get(row['skuId'],{}).get('shortTitle')})
  return out
 def status(self,plan_id):
  p=self.plan(plan_id);scope=p['scope'];_,all_rows=source_context(self.state,scope['auditId'],scope['auditFingerprint']);rows=self.coverage(p)
  return {'planId':plan_id,'fingerprint':p['fingerprint'],'auditId':scope['auditId'],'runtimeVersion':scope['runtimeVersion'],'onSaleSkuCount':len(rows),'offSaleSiblingCount':len(all_rows)-len(rows),'nativeIssueCount':sum(r['nativeTitleIssue'] is True for r in rows),'reviewedCopyCount':len(scope['changes']),'awaitingCopyCount':sum(r['state']=='awaiting-copy' for r in rows),'unknownTitleIssueCount':sum(r['state']=='unknown-title-issue' for r in rows),'batchCount':len(scope['chunks']),'noCopyWork':not scope['changes'] and not any(r['nativeTitleIssue'] is True or r['nativeTitleIssue'] is None for r in rows),'planningOnly':True,'writeExecutionAvailable':False,'imported':False,'originalShortTitlesVerified':False,'dedupAgainstUnchangedTitlesVerified':False,'historicalAuditCapture':True,'summaryOnly':True,'rowsCommand':'short-title-rows'}
 def rows(self,plan_id,*,page=1,page_size=50,view='coverage'):
  if type(page) is not int or not 1<=page<=1000000 or type(page_size) is not int or not 1<=page_size<=200 or view not in ('coverage','chunks','siblings'):raise SafetyError('bounded-short-title-plan-page-required')
  p=self.plan(plan_id);rows=self.coverage(p,include_offsale=view=='siblings') if view in ('coverage','siblings') else [{'batch':i+1,'rowCount':len(r),'skuIds':[row['skuId'] for row in r]} for i,r in enumerate(p['scope']['chunks'])];start=(page-1)*page_size;items=rows[start:start+page_size]
  return {'planId':plan_id,'view':view,'total':len(rows),'items':items,'page':page,'pageSize':page_size,'nextPage':page+1 if start+len(items)<len(rows) else None,'pageIsWholeScope':page==1 and len(items)==len(rows),'planningOnly':True}
 def compile(self,plan_id,template_path):
  from .short_title_workbook import compile_template,MAX_BYTES
  with FileLock(self.state/'short-title-workbook.lock'):
   p=self.plan(plan_id);path=Path(template_path)
   if not path.is_file() or path.stat().st_size>MAX_BYTES:raise SafetyError('bounded-local-short-title-template-required')
   raw=path.read_bytes();template_sha=hashlib.sha256(raw).hexdigest();artifacts=[]
   for number,chunk in enumerate(p['scope']['chunks'],1):
    data=compile_template(raw,[{'skuId':r['skuId'],'shortTitle':r['shortTitle']} for r in chunk]);sha=hashlib.sha256(data).hexdigest();relative='short-title-workbooks/'+plan_id+'/'+sha+'.xlsx';output=safe_join(self.state,relative);output.parent.mkdir(parents=True,exist_ok=True)
    try:
     with output.open('xb') as f:f.write(data)
    except FileExistsError:pass
    if file_sha(output)!=sha:raise SafetyError('short-title-workbook-source-conflict')
    artifacts.append({'batch':number,'rowCount':len(chunk),'localPath':relative,'sha256':sha,'rowsSha256':digest(chunk)})
   return {'planId':plan_id,'fingerprint':p['fingerprint'],'templateSha256':template_sha,'workbookCount':len(artifacts),'artifacts':artifacts,'planningOnly':True,'readyForImport':False,'templateOriginVerified':False,'writeExecutionAvailable':False,'imported':False,'merchantManualUploadRequested':False}
