"""Version-bound official CLI transports; upstream source is never persisted."""
from __future__ import annotations
import hashlib,json,re,subprocess
from pathlib import Path
from .safety import SafetyError,read_json,safe_join,file_sha,redact

AUDITED_SOURCES={'0.3.7':'abcc6fe5a354d14c4a9b99a221d0b682759d77e8200fc3922f0c1ce32e86a0b2'}
MAX_BUSINESS_BYTES=8*1024*1024
MAX_SOURCE_BYTES=2*1024*1024
MAX_ENVELOPE_BYTES=16*1024*1024
MAX_ARGV_UNITS=24000

def normalize_operation(profile,operation,*,write_authorized=False):
 from .official import validate_profile,validate_route
 validate_profile(profile)
 if not profile.startswith('merchant-'):raise SafetyError('merchant-owned-profile-namespace-required')
 if not isinstance(operation,dict) or set(operation)-{'url','method','params','body','skillId'}:raise SafetyError('invalid-business-operation')
 method=str(operation.get('method','GET')).upper()
 if method not in ('GET','POST','PUT','PATCH','DELETE'):raise SafetyError('invalid-http-method')
 if method!='GET' and not write_authorized:raise SafetyError('explicit-shop-write-approval-required')
 result={'url':validate_route(operation.get('url')),'method':method,'params':operation.get('params',{}),'skillId':operation.get('skillId','jdo-seller-info')}
 if not isinstance(result['params'],dict) or not isinstance(result['skillId'],str) or not re.fullmatch('[a-z0-9-]+',result['skillId']):raise SafetyError('invalid-business-payload')
 if operation.get('body') is not None:
  if method=='GET' or not isinstance(operation['body'],(dict,list)):raise SafetyError('invalid-business-payload')
  result['body']=operation['body']
 if redact(result)!=result:raise SafetyError('credentials-not-allowed-in-business-payload')
 raw=json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
 if len(raw)>MAX_BUSINESS_BYTES:raise SafetyError('business-payload-exceeds-local-memory-bound-use-reviewed-chunks')
 return result

def invoke_args(profile,operation):
 args=['invoke','--profile',profile,'--skill-id',operation['skillId'],'--url',operation['url'],'--method',operation['method'],'--params',json.dumps(operation['params'],ensure_ascii=False,separators=(',',':'),allow_nan=False),'--request-identity','vender','--timeout','30']
 if 'body' in operation:args+=['--body',json.dumps(operation['body'],ensure_ascii=False,separators=(',',':'),allow_nan=False)]
 if operation['method']!='GET':args+=['--yes']
 return args

def transport_for(executable,profile,operation):
 from .official import BASE
 args=[str(executable),'--endpoint',BASE.rstrip('/'),*invoke_args(profile,operation)]
 units=len(subprocess.list2cmdline(args).encode('utf-16-le'))//2
 return 'official-source-stdin' if units>MAX_ARGV_UNITS else 'official-binary'

def binary_execution(state,platform_name,transport):
 receipt=read_json(Path(state)/'tools/official.json',{})
 if not receipt:raise SafetyError('official-cli-not-installed-or-modified')
 exe=safe_join(safe_join(state,receipt['root']),receipt['executable'])
 if not exe.is_file() or file_sha(exe)!=receipt.get('executableSha256'):raise SafetyError('official-cli-not-installed-or-modified')
 return {'transport':transport,'officialVersion':receipt['version'],'platform':platform_name,'binarySha256':receipt['executableSha256'],'binaryArchiveSha256':receipt.get('archiveSha256')}

def source_manifest(policy,execution):
 source=policy.get('artifacts',{}).get('cli',{});binary=policy.get('artifacts',{}).get('binaries',{}).get(execution['platform'],{})
 version=execution['officialVersion']
 if policy.get('product')!='jdo-cli' or policy.get('stableVersion')!=version or source.get('version')!=version or binary.get('version')!=version or binary.get('sha256')!=execution['binaryArchiveSha256']:raise SafetyError('official-source-binary-policy-version-mismatch')
 if source.get('path')!='cli/jdo-cli' or source.get('sha256')!=AUDITED_SOURCES.get(version) or version not in AUDITED_SOURCES:raise SafetyError('official-source-not-audited-for-this-version')
 if not isinstance(source.get('deprecated'),bool):raise SafetyError('official-source-status-unknown')
 return {**execution,'sourceSha256':source['sha256'],'sourcePath':source['path'],'sourceStatus':'deprecated' if source['deprecated'] else 'current'}

def validate_source(raw,execution):
 version=execution.get('officialVersion');sha=execution.get('sourceSha256')
 if version not in AUDITED_SOURCES or sha!=AUDITED_SOURCES[version] or not isinstance(raw,bytes) or not raw or len(raw)>MAX_SOURCE_BYTES or hashlib.sha256(raw).hexdigest()!=sha:raise SafetyError('official-source-sha-not-verified')
 try:return raw.decode('utf-8-sig')
 except UnicodeError:raise SafetyError('official-source-encoding-invalid') from None


def validate_expected_shop(value,profile):
 if not isinstance(value,dict) or set(value)!={'profile','venderId','shopId','shopName'} or value['profile']!=profile or not isinstance(value['shopName'],str) or not value['shopName'].strip() or len(value['shopName'])>512 or any(isinstance(value[k],bool) or not str(value[k]).isdigit() for k in ('venderId','shopId')):raise SafetyError('complete-approved-shop-identity-required')
 return {k:str(v) for k,v in value.items()}

def matches_shop(actual,expected):
 return actual.get('shopType')=='POP' and all(str(actual.get(k))==str(expected[k]) for k in ('venderId','shopId','shopName'))

def publish_response(response,operation,secrets=()):
 # Omit request echoes, not actual acknowledgement identifiers/status evidence.
 body=operation.get('body');long_values=set()
 def collect(value):
  if isinstance(value,str) and len(value)>=1024:long_values.add(value)
  elif isinstance(value,dict):
   for child in value.values():collect(child)
  elif isinstance(value,list):
   for child in value:collect(child)
 collect(body);collect(operation.get('params',{}))
 def clean(value):
  if isinstance(value,(dict,list)) and body is not None and value==body:return None
  if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
  if isinstance(value,list):return [clean(v) for v in value]
  if not isinstance(value,str):return value
  if value in long_values or (len(long_values)>256 and len(value)>=1024):return '[REQUEST DATA OMITTED]'
  if value.lstrip().startswith(('{','[')):
   try:
    decoded=json.loads(value);filtered=clean(decoded)
    if decoded!=filtered:return json.dumps(filtered,ensure_ascii=False,separators=(',',':'))
   except (ValueError,TypeError,RecursionError):pass
  for original in long_values:
   if len(original)<=len(value) and original in value:value=value.replace(original,'[REQUEST DATA OMITTED]')
  return value
 return redact(clean(response),secrets)
