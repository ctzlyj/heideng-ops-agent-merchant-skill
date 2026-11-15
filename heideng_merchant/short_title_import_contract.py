"""Projection of native import responses; private bodies/URLs never leave the browser."""
import math,re,urllib.parse
from datetime import datetime,timezone,timedelta
from .safety import SafetyError
from .short_title_browser_contract import source_url,sha_bytes,INSTANCE_FIELDS,task_page

def timestamp(value):
 if type(value) in (int,float):
  result=float(value)
  if result>100000000000:result/=1000
 elif isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',value):
  try:result=datetime.strptime(value,'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=8))).timestamp()
  except ValueError:return None
 else:return None
 return result if math.isfinite(result) and result>0 else None

def object_sha(url):
 if not source_url(url,template=True):return None
 p=urllib.parse.urlsplit(url);return sha_bytes(urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,'','')).encode())

def instance_evidence(value):
 if not isinstance(value,dict):return 'absent',None
 found=set();present=False
 for key in INSTANCE_FIELDS:
  if key in value:
   present=True;ident=value[key]
   if type(ident) not in (str,int) or not re.fullmatch('[1-9][0-9]{5,18}',str(ident)) or int(ident)>9223372036854775807:return 'contradictory',None
   found.add(str(ident))
 if not present:return 'absent',None
 return ('exact',next(iter(found))) if len(found)==1 else ('contradictory',None)

def project(raw,data,phase):
 if phase not in ('upload','create'):raise SafetyError('native-import-phase-required')
 code=data.get('code') if isinstance(data,dict) else None;accepted=type(code) in (int,str) and code in (200,'200');outcome='accepted' if accepted else 'non-success' if type(code) in (int,str) else 'unknown';obj=None;instance=None;instance_state='not-applicable'
 if phase=='create':instance_state,instance=instance_evidence(data.get('data') if isinstance(data,dict) else None)
 if accepted and phase=='upload':
  payload=data.get('data')
  hashes=set()
  def visit(value,depth=0):
   if depth>20:raise SafetyError('bounded-upload-source-required')
   if isinstance(value,str):
    h=object_sha(value)
    if h:hashes.add(h)
   elif isinstance(value,dict):
    for key,child in value.items():
     if key in ('data','url','fileUrl','filePath','path','result'):visit(child,depth+1)
   elif isinstance(value,list):
    if len(value)>100:raise SafetyError('bounded-upload-source-required')
    for child in value:visit(child,depth+1)
  visit(payload)
  if len(hashes)==1:obj=next(iter(hashes))
  else:outcome='unknown'
 return {'outcome':outcome,'responseSha256':sha_bytes(raw),'uploadedObjectSha256':obj,'instanceId':instance,'instanceEvidence':instance_state}

def observed_tasks(data):
 clean=task_page(data)
 return [{**item,'startedAt':timestamp(row.get('jobExecTimeStart'))} for item,row in zip(clean,data['data']['batchJobRecordDtoList'])]
