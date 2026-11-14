"""Isolated, memory-only driver of audited official CLI main/parser/invoke."""
from __future__ import annotations
import contextlib,io,json,os,sys,time,math,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.safety import SafetyError,redact,read_json,safe_join
from heideng_merchant.official_transport import MAX_ENVELOPE_BYTES,normalize_operation,invoke_args,binary_execution,validate_source,validate_expected_shop,matches_shop,publish_response

class BoundedCapture(io.StringIO):
 def __init__(self):super().__init__();self.units=0
 def write(self,value):
  self.units+=len(value)
  if self.units>MAX_ENVELOPE_BYTES:raise SafetyError('official-captured-output-too-large')
  return super().write(value)

def execute_envelope(envelope,state,*,namespace_hook=None):
 if not isinstance(envelope,dict) or set(envelope)!={'schemaVersion','profile','operation','execution','source','writeAuthorized','approvalExpiresAt','expectedShop'} or envelope['schemaVersion']!=1:raise SafetyError('invalid-official-stdin-envelope')
 state=Path(state).resolve();home=safe_join(state,'cli-home')
 if os.name!='nt' or os.environ.get('JDO_CREDENTIAL_BACKEND')!='windows-credential-manager' or Path(os.environ.get('HOME','')).resolve()!=home or Path(os.environ.get('JDO_CLI_HOME','')).resolve()!=home/'.jdo-cli':raise SafetyError('official-stdin-native-credential-environment-required')
 if any(k in os.environ for k in ('JDO_APP_KEY','JDO_APP_SECRET','JDO_ACCESS_TOKEN','JDO_OAUTH_TOKEN_BASE_URL','JDO_ACCOUNT_IDENTITY','JDO_PIN')):raise SafetyError('ambient-official-credential-overrides-refused')
 profile=envelope['profile'];op=normalize_operation(profile,envelope['operation'],write_authorized=envelope['writeAuthorized'] is True)
 expected_shop=validate_expected_shop(envelope['expectedShop'],profile) if op['method']!='GET' else None
 deadline=envelope['approvalExpiresAt']
 if deadline is not None and (isinstance(deadline,bool) or not isinstance(deadline,(int,float)) or not math.isfinite(deadline)):raise SafetyError('invalid-approval-deadline')
 execution=envelope['execution']
 keys={'transport','officialVersion','platform','binarySha256','binaryArchiveSha256','sourceSha256','sourcePath','sourceStatus'}
 if not isinstance(execution,dict) or set(execution)!=keys or execution['transport']!='official-source-stdin' or execution['platform']!='windows-x64' or execution['sourcePath']!='cli/jdo-cli' or execution['sourceStatus'] not in ('deprecated','current'):raise SafetyError('invalid-official-execution-contract')
 actual=binary_execution(state,'windows-x64','official-source-stdin')
 if any(actual[k]!=execution[k] for k in actual):raise SafetyError('official-binary-changed-before-stdin-execution')
 if not isinstance(envelope['source'],str):raise SafetyError('official-source-text-required')
 source=validate_source(envelope['source'].encode('utf-8'),execution)
 receipt=read_json(state/'tools/official.json');exe=safe_join(safe_join(state,receipt['root']),receipt['executable'])
 namespace={'__name__':'_merchant_verified_official_cli','__file__':str(exe)}
 secrets=set();out=BoundedCapture();err=BoundedCapture();saved_argv=sys.argv;frozen_context=None
 def collect(context):
  if isinstance(context,dict):
   for key,value in context.items():
    if key in ('app_key','app_secret','access_token','refresh_token') and isinstance(value,str) and value:secrets.add(value)
    elif isinstance(value,dict):collect(value)
 def quiet(*a,**k):return None
 try:
  with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
   exec(compile(source,'<sha-verified-official-cli>','exec'),namespace)
   if namespace.get('CLI_VERSION')!=execution['officialVersion'] or not all(callable(namespace.get(k)) for k in ('main','cmd_invoke','get_auth_context','refresh_auth_context','execute_request_with_retry','log_event')):raise SafetyError('official-source-abi-not-compatible')
   for name in ('PLATFORM_APP_KEY','PLATFORM_APP_SECRET'):
    value=namespace.get(name)
    if isinstance(value,str) and value:secrets.add(value)
   if namespace_hook is not None:namespace_hook(namespace)
   original_auth=namespace['get_auth_context'];original_refresh=namespace['refresh_auth_context'];original_request=namespace['execute_request_with_retry']
   def auth(*a,**k):
    nonlocal frozen_context
    if frozen_context is not None:return frozen_context
    result=original_auth(*a,**k);collect(result)
    if expected_shop is None:return result
    if result.get('profile_name')!=profile or str(result.get('vender_id'))!=expected_shop['venderId']:raise SafetyError('authorized-credential-shop-mismatch')
    # Query the approved shop with this exact in-memory auth context, then keep
    # using it. A profile replacement during slow source/worker setup cannot
    # substitute different credentials between identity and business dispatch.
    frozen_context=result
    args=copy.copy(a[0]);args.method='GET';args.url='/rest/sp-seller/v0/venderinfo';args.params=json.dumps({'scopeSet':'baseInfo'});args.body=None;args.skill_id='jdo-seller-info';args.path_params=None
    identity_out=BoundedCapture()
    try:
     with contextlib.redirect_stdout(identity_out):namespace['cmd_invoke'](args)
     identity_response=json.loads(identity_out.getvalue())
     from heideng_merchant.official import identity_from_response
     from heideng_merchant.verification import business_payload
     business_payload(identity_response)
     if not matches_shop(identity_from_response(identity_response),expected_shop):raise SafetyError('live-authorized-shop-mismatch')
    finally:identity_out.close()
    return result
   def refresh(context,*a,**k):
    collect(context)
    try:return original_refresh(context,*a,**k)
    finally:collect(context)
   def request(factory,timeout,http_method,refresh_callback=None,retry_safe=False):
    # Preserve official signing/networking; forbid any second business write,
    # even a broad auth-marker response. Proactive OAuth refresh still works.
    writing=str(http_method).upper()!='GET'
    if writing and deadline is not None and time.time()>=deadline:raise SafetyError('approval-expired-before-official-request')
    return original_request(factory,timeout,http_method,refresh_callback=None if writing else refresh_callback,retry_safe=False if writing else retry_safe)
   namespace.update(get_auth_context=auth,refresh_auth_context=refresh,execute_request_with_retry=request,log_event=quiet,_maybe_report_telemetry=quiet)
   from heideng_merchant.official import BASE
   sys.argv=[str(exe),'--endpoint',BASE.rstrip('/'),*invoke_args(profile,op)]
   try:namespace['main']()
   except SystemExit as error:
    if error.code not in (None,0):raise SafetyError('official-invoke-outcome-unknown') from None
  result=json.loads(out.getvalue())
  if not isinstance(result,(dict,list)) or not result:raise SafetyError('official-invoke-response-missing')
  return {'ok':True,'response':publish_response(result,op,secrets),'execution':execution}
 except Exception:
  # Neither stderr nor exception text is evidence of a safe retry; discard it.
  return {'ok':False,'error':'official-invoke-outcome-unknown','execution':execution}
 finally:sys.argv=saved_argv;out.close();err.close();namespace.clear();secrets.clear()

def main():
 try:
  raw=sys.stdin.buffer.read(MAX_ENVELOPE_BYTES+1)
  if not raw or len(raw)>MAX_ENVELOPE_BYTES:raise SafetyError('official-stdin-envelope-too-large')
  envelope=json.loads(raw);state=Path(os.environ.get('HOME','')).resolve().parent
  result=execute_envelope(envelope,state)
 except Exception:result={'ok':False,'error':'official-stdin-rejected-or-outcome-unknown'}
 print(json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False))
 return 0 if result.get('ok') is True else 2
if __name__=='__main__':raise SystemExit(main())
