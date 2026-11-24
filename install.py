"""Agent runs this one-repository installer; no employee services required."""
from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
if __name__=='__main__' and sys.platform=='darwin':
 # The common metadata helper lives in __init__.py; check it before the first import.
 for entry in (ROOT/'heideng_merchant', ROOT/'heideng_merchant/__init__.py'):
  if getattr(entry.stat(),'st_flags',0) & 0x40000000:
   print(json.dumps({'status':'blocked','error':'macos-cloud-file-not-local','path':str(entry),'nextAction':'在访达中选择“现在下载”，下载后重新安装。'},ensure_ascii=False))
   raise SystemExit(2)
from heideng_merchant import VERSION,SKILL_NAME,CloudFileUnavailable,check_entry_modules,require_local
if __name__=='__main__':
 try:check_entry_modules(ROOT,('distribution','safety','state','official'))
 except CloudFileUnavailable as error:
  print(json.dumps(error.receipt(),ensure_ascii=False));raise SystemExit(2)
from heideng_merchant.distribution import install_archive,install_source,rollback
from heideng_merchant.safety import SafetyError,redact
from heideng_merchant.state import install_state
from heideng_merchant.official import OfficialClient

HOSTS={'workbuddy':('.workbuddy','skills'),'codex':('.codex','skills'),'claude':('.claude','skills'),'joycode':('.joycode','skills'),'universal':('.agents','skills')}

def target_directory(host,home=None,skills_dir=None):
 if skills_dir:return Path(skills_dir).resolve()/SKILL_NAME
 user=Path(home).resolve() if home else Path.home()
 if host=='codex' and not home and os.environ.get('CODEX_HOME'):return Path(os.environ['CODEX_HOME']).resolve()/'skills'/SKILL_NAME
 return user.joinpath(*HOSTS[host])/SKILL_NAME

def main(argv=None):
 for stream in (sys.stdout,sys.stderr):
  if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='backslashreplace')
 p=argparse.ArgumentParser(description='黑灯运营智能体商家版单仓库安装；由Agent执行')
 p.add_argument('--host',choices=HOSTS,default='codex');p.add_argument('--home');p.add_argument('--skills-dir');p.add_argument('--archive');p.add_argument('--sha256');p.add_argument('--offline',action='store_true');p.add_argument('--with-official',action='store_true');p.add_argument('--with-runtime',action='store_true');p.add_argument('--with-cutout-runtime',action='store_true',help='兼容保留；标准在线安装已包含神经抠图依赖与Lite权重准备');p.add_argument('--rollback',action='store_true');p.add_argument('--no-auto-update',action='store_true')
 p.add_argument('--state',type=Path,help='商家隔离状态目录')
 args=p.parse_args(argv)
 try:
  if sys.version_info<(3,11):raise SafetyError('python-3.11-or-newer-required-agent-install-official-runtime')
  if not args.archive and not args.rollback:
   require_local(ROOT,parents=True)
   for name in ('VERSION','package-files.json','SKILL.md'):
    require_local(ROOT/name)
  target=target_directory(args.host,args.home,args.skills_dir);state=install_state(target,args.home,args.state,check_runtime=not(args.offline or args.rollback))
  from heideng_merchant.safety import read_json
  existing_updates=read_json(state/'updates/settings.json',{})
  if existing_updates and existing_updates.get('target')!=str(target.resolve()):raise SafetyError('update-target-changed-use-explicit-isolated-state-or-maintenance-migration')
  if args.rollback:result=rollback(target,state)
  elif args.archive:
   if not args.sha256:raise SafetyError('downloaded-archive-needs-verified-sha256')
   result=install_archive(Path(args.archive),target,state,expected_sha=args.sha256)
  else:
   result=install_source(ROOT,target,state)
  client=OfficialClient(state)
  result['shopCapability']=client.shop_capability()
  if args.with_official and not args.offline:
   try:
    component=client.install()
    result['officialCli']={**component,'ready':client.ready(),'deferred':False}
   except (SafetyError,OSError,ValueError) as error:
    permitted={'official-platform-not-supported','official-network-unavailable','official-sha256-mismatch','official-version-mismatch','official-download-too-large','official-downgrade-refused','official-download-redirect-refused'}
    code=str(error) if isinstance(error,SafetyError) and str(error) in permitted else 'official-cli-install-step-failed'
    ready=client.ready()
    result['officialCli']={'status':'unavailable','ready':ready,'deferred':False,'reason':code}
    warning='Skill本体已安装；官方京麦CLI更新未完成，原已校验CLI仍可用，使用前按原版本核对。' if ready else 'Skill本体已安装；官方京麦CLI准备未完成。店铺官方链路不可用，离线任务仍可使用。'
    result['warnings']=[{'component':'officialCli','reason':code,'text':warning}]
  else:result['officialCli']={'ready':client.ready(),'deferred':True}
  if not args.offline:
   from heideng_merchant.runtime_dependencies import prepare_runtime,prepare_cutout_weights
   try:result['runtimeDependencies']=prepare_runtime(state,target,optional='cutout')
   except (SafetyError,OSError):
    result['runtimeDependencies']={'status':'deferred','independent':True,'reason':'runtime-dependency-preparation-unavailable','originalPackageAndStateRetained':True}
   else:
    try:result['cutoutPreparation']=prepare_cutout_weights(state,target)
    except (SafetyError,OSError):
     result['cutoutPreparation']={'status':'deferred','independent':True,'reason':'cutout-weight-preparation-unavailable','nextAction':'联网后从原安装目录执行 run materials -- prepare-cutout --download；不影响其他能力。'}
  else:result['runtimeDependencies']={'status':'deferred','independent':True,'reason':'offline-or-not-requested'}
  from heideng_merchant.update_client import configure, set_enabled, status as update_status
  trust_path=target/'updates/trust.json'
  if trust_path.is_file():
   configure(state,target,read_json(trust_path),host=args.host if not args.skills_dir else 'explicit-skills-dir')
   if args.no_auto_update:set_enabled(state,False)
   result['automaticUpdates']=update_status(state)
  else:result['automaticUpdates']={'enabled':False,'reason':'publisher-trust-not-configured'}
  result.update(skill=SKILL_NAME,stateRoot=str(state),statusArgv=[sys.executable,str(target/'scripts/merchant.py'),'--state',str(state),'status'],requiresManualCommands=False,employeeDependencies=False,next='可以告诉我店名了。')
  from heideng_merchant.mature_runtime import status as mature_status
  result['matureCapabilities']=mature_status()
  print(json.dumps(redact(result),ensure_ascii=False));return 0
 except CloudFileUnavailable as error:
  print(json.dumps(error.receipt(),ensure_ascii=False));return 2
 except (SafetyError,OSError,ValueError) as error:
  result={'status':'blocked','error':redact(str(error)),'internalVersionUntouched':True}
  if isinstance(error,SafetyError) and str(error)=='same-version-different-artifact':
   result.update(updateAction='obtain-newer-version',sameVersionReplacementAllowed=False,rollbackRequired=False,
                 guidance='已安装包和候选包版本号相同但内容不同，防替换校验保持启用。请使用版本号递增且来源和SHA已核验的候选包；不要为升级自动回滚、修改收据或关闭校验。')
  print(json.dumps(result,ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
