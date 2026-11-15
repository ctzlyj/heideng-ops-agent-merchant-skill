"""Explicit repair eligibility and captured original image byte evidence."""
import copy,hashlib,os,re
from .safety import SafetyError,safe_join,file_sha,redact,read_json

MAX_ORIGINAL_BYTES=64*1024*1024
MAX_CAPTURE_BYTES=256*1024*1024

def is_empty(content):
 values=content['textMaterial']['contents'] if content['materialType']==1002 else content['imageMaterial']['skuImages']
 return not values or (content['materialType']==1002 and not any(v.strip() for v in values))

def repair_allowed(content,evidence):
 return isinstance(content,dict) and isinstance(evidence,dict) and type(evidence.get('status')) is int and (evidence['status']==5 or (evidence['status']==4 and is_empty(content)))

def _download(url):
 from .workflows import _asset_download
 raw=_asset_download('https://img14.360buyimg.com/imgzone/'+url,require_complete=True)
 if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_ORIGINAL_BYTES:raise SafetyError('bounded-original-repair-image-bytes-required')
 return raw

def _cache(state,raw):
 sha=hashlib.sha256(raw).hexdigest();relative='sku-material-originals/'+sha+'.bin';path=safe_join(state,relative);path.parent.mkdir(parents=True,exist_ok=True)
 try:
  with path.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
 except FileExistsError:pass
 if not path.is_file() or file_sha(path)!=sha:raise SafetyError('original-repair-image-cache-conflict')
 return sha,relative

def repair_fields(ops,baseline,audit,changes):
 from .sku_material_contract import SLOTS,jfs
 repairs=[r for r in changes if r.get('action')=='repair']
 if not repairs:return {}
 originals={};seen={};total=0
 for row in repairs:
  sku=row['skuId'];kind,order=SLOTS[row['slot']];key=f'{kind}:{order}';old=baseline[sku].get(key)
  if not repair_allowed(old,audit[sku].get(key)):raise SafetyError('existing-rejected-or-approved-empty-slot-required')
  if kind==1002:continue
  entries=[]
  for image in old['imageMaterial']['skuImages']:
   url=jfs(image['imgUrl'])
   if url not in seen:
    raw=_download(url);total+=len(raw)
    if total>MAX_CAPTURE_BYTES:raise SafetyError('original-repair-image-capture-budget-exceeded')
    seen[url]=_cache(ops.state,raw)
   sha,relative=seen[url];entries.append({'index':image['index'],'url':url,'sha256':sha,'localPath':relative})
  originals.setdefault(sku,{})[key]=entries
 fields={'version':2,'baselineAudit':copy.deepcopy(audit),'repairSources':originals}
 fields['repairOriginals']=manifest(ops,original_set([fields]));return fields

def validate_repairs(ops,proof,sources,*,live=False):
 from .sku_material_contract import SLOTS,jfs,hash_value
 repairs=[r for r in proof['changes'] if r.get('action')=='repair']
 if proof['version']==1:
  if repairs:raise SafetyError('repair-requires-v2-original-proof')
  return
 if not repairs:raise SafetyError('v2-repair-proof-needs-explicit-repair')
 audit=proof['baselineAudit'];baseline=proof['baseline'];originals=proof['repairSources']
 if not isinstance(audit,dict) or set(audit)!=set(baseline) or not isinstance(originals,dict):raise SafetyError('complete-original-repair-audit-required')
 for sku,slots in audit.items():
  if not isinstance(slots,dict) or set(slots)!=set(baseline[sku]):raise SafetyError('complete-original-repair-slot-audit-required')
  for evidence in slots.values():
   if not isinstance(evidence,dict) or set(evidence)!={'status','reason'} or (evidence['status'] is not None and type(evidence['status']) is not int) or not isinstance(evidence['reason'],str) or redact(evidence['reason'])!=evidence['reason']:raise SafetyError('canonical-original-repair-audit-required')
 expected={};checked={}
 for row in repairs:
  sku=row['skuId'];kind,order=SLOTS[row['slot']];key=f'{kind}:{order}';old=baseline[sku].get(key)
  if not repair_allowed(old,audit[sku].get(key)):raise SafetyError('existing-rejected-or-approved-empty-slot-required')
  if kind==1002:
   if row['text'] in old['textMaterial']['contents']:raise SafetyError('repair-text-must-change-original-content')
   continue
  entries=originals.get(sku,{}).get(key)
  if not isinstance(entries,list) or len(entries)!=len(old['imageMaterial']['skuImages']):raise SafetyError('all-original-repair-image-bytes-required')
  expected.setdefault(sku,{})[key]=entries;new=sources[row['uploadTaskId']]
  for entry,image in zip(entries,old['imageMaterial']['skuImages']):
   if not isinstance(entry,dict) or set(entry)!={'index','url','sha256','localPath'} or entry['index']!=image['index'] or entry['url']!=jfs(image['imgUrl']):raise SafetyError('original-repair-image-binding-mismatch')
   sha=entry['sha256'];relative='sku-material-originals/'+str(sha)+'.bin'
   if not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha) or entry['localPath']!=relative:raise SafetyError('canonical-original-repair-image-cache-required')
   path=safe_join(ops.state,relative)
   if not path.is_file() or file_sha(path)!=sha:raise SafetyError('original-repair-image-bytes-lost-or-changed')
   if new['url']==entry['url'] or new['originalSha256']==sha:raise SafetyError('repair-image-must-change-original-url-and-bytes')
   if live:
    if entry['url'] not in checked:checked[entry['url']]=hashlib.sha256(_download(entry['url'])).hexdigest()
    if checked[entry['url']]!=sha:raise SafetyError('original-repair-image-remote-bytes-changed')
 if hash_value(originals)!=hash_value(expected):raise SafetyError('exact-original-repair-image-scope-required')
 complete=load_manifest(ops,proof['repairOriginals']);own=original_set([proof])
 if any(entry not in complete for entry in own):raise SafetyError('complete-approved-original-image-set-required')
 for entry in complete:
  if not safe_join(ops.state,entry['localPath']).is_file() or file_sha(safe_join(ops.state,entry['localPath']))!=entry['sha256']:raise SafetyError('complete-original-image-cache-lost-or-changed')
  if live:
   if entry['url'] not in checked:checked[entry['url']]=hashlib.sha256(_download(entry['url'])).hexdigest()
   if checked[entry['url']]!=entry['sha256']:raise SafetyError('complete-original-image-remote-bytes-changed')
 old_urls={entry['url'] for entry in complete};old_hashes={entry['sha256'] for entry in complete}
 for row in repairs:
  if 'uploadTaskId' in row:
   new=sources[row['uploadTaskId']]
   if new['url'] in old_urls or new['originalSha256'] in old_hashes:raise SafetyError('repair-image-must-differ-from-every-approved-original')

def check_live_audit(proof,snapshot):
 from .sku_material_contract import SLOTS
 if proof['version']!=2:return
 for row in proof['changes']:
  if row.get('action')!='repair':continue
  sku=row['skuId'];kind,order=SLOTS[row['slot']];key=f'{kind}:{order}'
  if snapshot['audit'][sku].get(key)!=proof['baselineAudit'][sku].get(key):raise SafetyError('original-repair-audit-status-or-reason-changed')


def check_original_scope(proof):
 from .sku_material_contract import SLOTS,jfs,hash_value
 if proof.get('version')!=2 or ('baseline' not in proof and 'changes' not in proof):return
 if not isinstance(proof.get('baseline'),dict) or not isinstance(proof.get('changes'),list) or not isinstance(proof.get('repairSources'),dict):raise SafetyError('complete-other-child-original-image-scope-required')
 expected={}
 for row in proof['changes']:
  if row.get('action')!='repair':continue
  sku=row['skuId'];kind,order=SLOTS[row['slot']];key=f'{kind}:{order}'
  if kind==1002:continue
  old=proof['baseline'].get(sku,{}).get(key);entries=proof['repairSources'].get(sku,{}).get(key)
  if not isinstance(old,dict) or not isinstance(entries,list) or len(entries)!=len(old['imageMaterial']['skuImages']):raise SafetyError('all-other-child-original-image-bytes-required')
  for entry,image in zip(entries,old['imageMaterial']['skuImages']):
   if not isinstance(entry,dict) or entry.get('url')!=jfs(image['imgUrl']) or entry.get('index')!=image['index']:raise SafetyError('other-child-original-image-slot-binding-mismatch')
  expected.setdefault(sku,{})[key]=entries
 if hash_value(expected)!=hash_value(proof['repairSources']):raise SafetyError('exact-other-child-original-image-scope-required')

def original_set(proofs):
 entries={}
 for proof in proofs:
  check_original_scope(proof)
  sources=proof.get('repairSources',{})
  if not isinstance(sources,dict):raise SafetyError('canonical-repair-original-source-map-required')
  for slots in sources.values():
   if not isinstance(slots,dict):raise SafetyError('canonical-repair-original-slot-map-required')
   for images in slots.values():
    if not isinstance(images,list):raise SafetyError('canonical-repair-original-array-required')
    for image in images:
     if not isinstance(image,dict) or set(image)!={'index','url','sha256','localPath'}:raise SafetyError('canonical-repair-original-image-required')
     entry={k:image[k] for k in ('url','sha256','localPath')}
     if entry['url'] in entries and entries[entry['url']]!=entry:raise SafetyError('conflicting-global-original-image-proof')
     entries[entry['url']]=entry
 return [entries[url] for url in sorted(entries)]

def manifest(ops,entries):
 from .sku_material_contract import hash_value
 from .video_delivery import _once
 sha=hash_value(entries);relative='sku-material-originals/global-'+sha+'.json';path=safe_join(ops.state,relative);prior=read_json(path)
 if prior is None:_once(path,entries)
 elif prior!=entries:raise SafetyError('original-image-manifest-conflict')
 return {'sha256':sha,'localPath':relative}

def load_manifest(ops,reference):
 from .sku_material_contract import hash_value,jfs
 if not isinstance(reference,dict) or set(reference)!={'sha256','localPath'} or not isinstance(reference['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',reference['sha256']) or reference['localPath']!='sku-material-originals/global-'+reference['sha256']+'.json':raise SafetyError('canonical-original-image-manifest-required')
 entries=read_json(safe_join(ops.state,reference['localPath']))
 if not isinstance(entries,list) or hash_value(entries)!=reference['sha256']:raise SafetyError('original-image-manifest-lost-or-changed')
 for entry in entries:
  if not isinstance(entry,dict) or set(entry)!={'url','sha256','localPath'} or jfs(entry['url'])!=entry['url'] or not isinstance(entry['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',entry['sha256']) or entry['localPath']!='sku-material-originals/'+entry['sha256']+'.bin':raise SafetyError('canonical-global-original-image-entry-required')
 if entries!=sorted(entries,key=lambda entry:entry['url']) or len({e['url'] for e in entries})!=len(entries):raise SafetyError('unique-ordered-global-original-images-required')
 return entries

def finalize_proofs(ops,shop,proofs):
 from .sku_material_contract import body_from_proof
 reference=manifest(ops,original_set(proofs)) if any(p['version']==2 for p in proofs) else None
 for proof in proofs:
  if proof['version']==2:proof['repairOriginals']=reference
 return [(proof,body_from_proof(ops,shop,proof)[0]) for proof in proofs]

def validate_scope_originals(ops,scope):
 from .sku_material_contract import hash_value
 proof=scope['skuMaterialInput'];ih=proof['intentHash'];outer=scope.get('shopMaterialInput');folder='shop-material' if outer is not None else 'sku-material'
 index=read_json(safe_join(ops.state,folder+'-intents/'+(ih[:24] if outer is not None else ih)+'.json'))
 if not isinstance(index,dict) or not isinstance(index.get('planId'),str) or not re.fullmatch('[a-f0-9]{24}',index['planId']):raise SafetyError('original-repair-parent-registration-required')
 plan=read_json(safe_join(ops.state,folder+'-plans/'+index['planId']+'.json'))
 if not isinstance(plan,dict) or plan.get('fingerprint')!=hash_value(plan.get('scope')) or plan.get('planId')!=plan['fingerprint'][:24] or plan['scope'].get('intentHash')!=ih:raise SafetyError('original-global-repair-parent-required')
 captured=None
 if outer is not None:
  from .shop_material_execution_contract import source_context
  i=plan['scope']['intent'];captured=source_context(ops,i['auditId'],i['auditFingerprint'])['scope']['sources']['materials']
 proofs=[]
 for ref in plan['scope']['tasks']:
  task=read_json(ops._path(ref['taskId']))
  if not isinstance(task,dict) or task.get('fingerprint')!=ref['fingerprint'] or task.get('taskId')!=ref['taskId'] or hash_value(task.get('scope'))!=ref['fingerprint'] or task['scope'].get('shop')!=scope['shop']:raise SafetyError('original-global-repair-child-proof-required')
  child=task['scope'].get('skuMaterialInput')
  if not isinstance(child,dict) or child.get('intentHash')!=ih:raise SafetyError('global-repair-child-parent-mismatch')
  if captured is not None:
   if child.get('baseline')!={sku:captured['contents'][sku] for sku in child['skuIds']}:raise SafetyError('global-repair-child-original-audit-content-mismatch')
   if child.get('version')==2 and child.get('baselineAudit')!={sku:captured['audit'][sku] for sku in child['skuIds']}:raise SafetyError('global-repair-child-original-audit-status-mismatch')
  proofs.append(child)
 expected=original_set(proofs)
 for child in proofs:
  if child['version']==2 and load_manifest(ops,child['repairOriginals'])!=expected:raise SafetyError('complete-root-original-image-manifest-required')
