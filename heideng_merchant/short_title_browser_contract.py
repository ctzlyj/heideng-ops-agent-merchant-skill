"""Bounded, nonsecret short-title browser evidence; never a write approval."""
from __future__ import annotations
import hashlib,json,re,urllib.parse
from .safety import SafetyError,redact
from .short_title_contract import identifier

MAX_JSON=1024*1024
MAX_TASK_ROWS=500
INSTANCE_FIELDS=('taskId','taskInstanceId','batchJobId','jobInstanceId','jobExecId')
RPC_METHODS={'file.upload':('file.upload','dsm.base.service.file.upload'),'batchJobService.createImportJob':('batchJobService.createImportJob','dsm.product.manage.view.batchJobService.createImportJob'),'batchJobService.queryByPage':('batchJobService.queryByPage','dsm.product.manage.view.batchJobService.queryByPage')}

def sha_bytes(value):return hashlib.sha256(value).hexdigest()

def source_url(url,*,template=False,service=None):
 if not isinstance(url,str) or not 1<=len(url)<=16384 or any(ord(c)<33 for c in url):return False
 try:
  p=urllib.parse.urlsplit(url);host=(p.hostname or '').lower();port=p.port
 except ValueError:return False
 if p.scheme!='https' or p.username or p.password or port not in (None,443) or p.fragment:return False
 hosts={'jingmai.jd.com','api.m.jd.com','wares-jdm.jd.com'}
 if template:hosts.add('storage.jd.com')
 if host not in hosts and not (template and re.fullmatch(r'img[1-9][0-9]?\.360buyimg\.com',host)):return False
 if service:
  q=urllib.parse.parse_qs(p.query,keep_blank_values=True)
  if not isinstance(service,str):return False
  methods=q.get('method');allowed=RPC_METHODS.get(service,(service,))
  return isinstance(methods,list) and len(methods)==1 and methods[0] in allowed and p.path in ('/api','/api/')
 return True

def response_bytes(response,page,*,service=None):
 try:
  if response.status!=200 or response.request.resource_type not in ('fetch','xhr') or response.request.frame.page is not page or response.request.frame is not page.main_frame or not source_url(response.url,service=service):raise SafetyError('owned-bounded-browser-json-response-required')
  content=response.header_value('content-type') or ''
  if not re.fullmatch(r'application/(?:[a-z0-9.-]+\+)?json(?:\s*;.*)?',content.lower()):raise SafetyError('browser-json-content-type-required')
  size=response.header_value('content-length')
  if size is not None and (not size.isdigit() or int(size)>MAX_JSON):raise SafetyError('bounded-browser-response-required')
  if response.finished() is not None:raise SafetyError('complete-browser-response-required')
  encoding=response.header_value('content-encoding') or 'identity'
  raw=response.body()
  if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_JSON:raise SafetyError('bounded-browser-response-required')
  if encoding.lower()=='identity' and size is not None and int(size)!=len(raw):raise SafetyError('complete-browser-response-required')
  def unique_pairs(pairs):
   out={}
   for key,value in pairs:
    if key in out:raise SafetyError('ambiguous-browser-json-object-refused')
    out[key]=value
   return out
  data=json.loads(raw,object_pairs_hook=unique_pairs,parse_constant=lambda value:(_ for _ in ()).throw(SafetyError('nonfinite-browser-json-refused')))
  if not isinstance(data,(dict,list)):raise SafetyError('browser-json-object-required')
  return raw,data
 except Exception:raise SafetyError('owned-bounded-browser-json-response-required') from None

def identity_observation(data,shop):
 """No merging across dictionaries and no inferred/legacy numeric POP type."""
 found=False;foreign=False;visited=0
 def visit(value,depth=0):
  nonlocal found,foreign,visited
  visited+=1
  if visited>10000 or depth>30:raise SafetyError('bounded-browser-identity-required')
  if isinstance(value,dict):
   if 'shopName' in value and ('venderId' in value or 'vendorId' in value):
    try:
     vid=identifier(value.get('venderId'));sid=identifier(value.get('shopId'))
     if 'vendorId' in value and identifier(value['vendorId'])!=vid:raise SafetyError('contradictory-vender-identity')
     matches=value['shopName']==shop['shopName'] and vid==shop['venderId'] and sid==shop['shopId'] and value.get('shopType')=='POP'
    except SafetyError:matches=False
    found=found or matches;foreign=foreign or not matches
   for child in value.values():
    if isinstance(child,(dict,list)):visit(child,depth+1)
  elif isinstance(value,list):
   for child in value:visit(child,depth+1)
 visit(data);return found,foreign

def task_page(data):
 if not isinstance(data,dict) or type(data.get('code')) not in (int,str) or data.get('code') not in (200,'200') or not isinstance(data.get('data'),dict):raise SafetyError('accepted-short-title-task-page-required')
 rows=data['data'].get('batchJobRecordDtoList')
 if not isinstance(rows,list) or len(rows)>MAX_TASK_ROWS or any(not isinstance(r,dict) for r in rows):raise SafetyError('bounded-original-short-title-task-rows-required')
 out=[];seen=set()
 for row in rows:
  ids=set()
  for key in INSTANCE_FIELDS:
   if key in row:
    value=row[key]
    if type(value) not in (int,str) or not re.fullmatch(r'[1-9][0-9]{5,18}',str(value)) or int(value)>9223372036854775807:raise SafetyError('precise-short-title-task-instance-id-required')
    ids.add(str(value))
  if len(ids)>1:raise SafetyError('unambiguous-short-title-task-instance-required')
  instance=next(iter(ids)) if ids else None
  if instance is not None and instance in seen:raise SafetyError('unique-short-title-task-instance-required')
  if instance:seen.add(instance)
  url=row.get('jobExecFileSrc');source=None
  if source_url(url,template=True):
   p=urllib.parse.urlsplit(url);public=urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,'',''));source=sha_bytes(public.encode())
  out.append({'instanceId':instance,'uploadedObjectSha256':source})
 return out

def shop_checked(shop):
 from .official import validate_profile
 if not isinstance(shop,dict) or set(shop)!={'profile','shopName','venderId','shopId'} or redact(shop)!=shop:raise SafetyError('exact-nonsecret-short-title-shop-required')
 validate_profile(shop['profile'])
 if not shop['profile'].startswith('merchant-') or not isinstance(shop['shopName'],str) or not shop['shopName'].strip():raise SafetyError('owned-merchant-short-title-shop-required')
 return {**shop,'venderId':identifier(shop['venderId']),'shopId':identifier(shop['shopId'])}
