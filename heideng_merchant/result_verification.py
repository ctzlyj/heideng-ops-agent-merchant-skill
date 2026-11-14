"""Approved result-ID references only; no expression evaluation or URL substitution."""
import copy,json,re
from .safety import SafetyError,redact
from .verification import business_payload,validate_expected

def result_field(value):
 if not isinstance(value,dict) or set(value)!={'$result'} or not isinstance(value['$result'],str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}',value['$result']) or redact({value['$result']:'synthetic'})!={value['$result']:'synthetic'}:raise SafetyError('safe-top-level-result-id-reference-required')
 return value['$result']

def resource_id(value):
 if isinstance(value,bool) or not isinstance(value,(str,int)) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',str(value)) or str(value)=='0':raise SafetyError('actual-safe-resource-id-required')
 return str(value)

def validate_result_verification(value,normalize):
 if not isinstance(value,dict) or set(value)!={'query','expected'}:raise SafetyError('complete-result-readback-scope-required')
 query=normalize(value['query']);expected=value['expected']
 if query['method']!='GET' or not isinstance(expected,dict) or not expected or len(expected)>128:raise SafetyError('readonly-result-readback-required')
 refs=set();preview=copy.deepcopy(expected)
 for name,val in query['params'].items():
  if isinstance(val,dict) and any(str(k).startswith('$') for k in val):
   field=result_field(val)
   if '{'+name+'}' not in query['url']:raise SafetyError('result-id-must-bind-approved-path-param')
   refs.add(field)
 if not refs:raise SafetyError('result-readback-needs-original-receipt-id')
 for name,val in expected.items():
  if isinstance(val,dict) and '$result' in val:
   if result_field(val) not in refs:raise SafetyError('result-expected-id-must-also-bind-query')
   preview[name]='1'
 validate_expected(preview)
 result={'query':query,'expected':copy.deepcopy(expected)}
 if redact(result)!=result or len(json.dumps(result,ensure_ascii=False,allow_nan=False))>65536:raise SafetyError('bounded-nonsecret-result-readback-required')
 return result

def resolve_result_verification(scope,result):
 data=business_payload(result)
 if not isinstance(data,dict):raise SafetyError('single-original-result-object-required')
 resolved=copy.deepcopy(scope)
 for section in (resolved['query']['params'],resolved['expected']):
  for name,value in list(section.items()):
   if isinstance(value,dict) and '$result' in value:
    field=result_field(value)
    if field not in data:raise SafetyError('original-receipt-id-missing')
    section[name]=resource_id(data[field])
 validate_expected(resolved['expected']);return resolved
