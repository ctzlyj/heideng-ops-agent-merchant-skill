"""Agent runs this one-repository installer; no employee services required."""
from __future__ import annotations
import argparse,json,os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from heideng_merchant import VERSION,SKILL_NAME
from heideng_merchant.distribution import build_bundle,install_archive,rollback
from heideng_merchant.safety import SafetyError,file_sha,redact
from heideng_merchant.state import merchant_home
from heideng_merchant.official import OfficialClient

HOSTS={'codex':('.codex','skills'),'claude':('.claude','skills'),'joycode':('.agents','skills'),'universal':('.agents','skills')}

def target_directory(host,home=None,skills_dir=None):
 if skills_dir:return Path(skills_dir).resolve()/SKILL_NAME
 user=Path(home).resolve() if home else Path.home()
 if host=='codex' and not home and os.environ.get('CODEX_HOME'):return Path(os.environ['CODEX_HOME']).resolve()/'skills'/SKILL_NAME
 return user.joinpath(*HOSTS[host])/SKILL_NAME

def main(argv=None):
 for stream in (sys.stdout,sys.stderr):
  if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='backslashreplace')
 p=argparse.ArgumentParser(description='黑灯运营智能体商家版单仓库安装；由Agent执行')
 p.add_argument('--host',choices=HOSTS,default='codex');p.add_argument('--home');p.add_argument('--skills-dir');p.add_argument('--archive');p.add_argument('--sha256');p.add_argument('--offline',action='store_true');p.add_argument('--with-official',action='store_true');p.add_argument('--rollback',action='store_true')
 args=p.parse_args(argv)
 try:
  if sys.version_info<(3,11):raise SafetyError('python-3.11-or-newer-required-agent-install-official-runtime')
  target=target_directory(args.host,args.home,args.skills_dir);state=merchant_home(args.home)
  if args.rollback:result=rollback(target,state)
  else:
   with tempfile.TemporaryDirectory(prefix='heideng-merchant-install-') as temporary:
    if args.archive:
     if not args.sha256:raise SafetyError('downloaded-archive-needs-verified-sha256')
     archive=Path(args.archive);sha=args.sha256
    else:
     source=Path(__file__).resolve().parent;version=(source/'VERSION').read_text(encoding='utf-8-sig').strip();archive=build_bundle(source,Path(temporary)/'merchant.zip',version);sha=file_sha(archive)
    result=install_archive(archive,target,state,expected_sha=sha)
  if args.with_official and not args.offline:result['officialCli']=OfficialClient(state).install()
  else:result['officialCli']={'ready':OfficialClient(state).ready(),'deferred':True}
  result.update(skill=SKILL_NAME,requiresManualCommands=False,employeeDependencies=False,next='由Agent运行已安装scripts/merchant.py onboarding；需要店铺时自动补官方CLI，商家只扫码。')
  print(json.dumps(redact(result),ensure_ascii=False));return 0
 except (SafetyError,OSError,ValueError) as error:
  print(json.dumps({'status':'blocked','error':redact(str(error)),'internalVersionUntouched':True},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
