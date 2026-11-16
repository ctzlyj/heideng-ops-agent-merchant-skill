"""Local copy of the mover 1.2.6 large-request interface checks.

A fingerprint identifies cached evidence, not an allowed CLI release. The native
CLI handles small bodies; only embedded bytecode requires a real 3.12 host.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

COMMAND_LINE_BODY_LIMIT=30000
NEEDED_ATTRIBUTES=('url','method','params','body','path_params','profile','skill_id','request_identity','timeout','dry_run','yes')
LOGIN_ATTRIBUTES=('profile','shop_name','no_browser','timeout')
AFFECTED=['属性补全','素材绑定','整版编辑']
UNAFFECTED=['查询','审计','授权','本地生成','短标题导入','批量抠图']

_PROBE_SOURCE = r"""
import sys,json,marshal,dis
from pathlib import Path
if sys.version_info[:2] != (3,12):sys.exit(2)
ns={"__name__":"jdo_cli_embedded","__file__":"jdo-cli.py"}
exec(marshal.loads(Path(sys.argv[1]).read_bytes()),ns)
def inspect_function(name):
    f=ns.get(name);code=getattr(f,'__code__',None)
    # Official CLI reads some fields with getattr or delegates them to local helpers.
    # Traverse only static code objects: never execute those account/request helpers.
    visited=set();attrs=set()
    def visit(func):
        c=getattr(func,'__code__',None)
        if c is None or id(c) in visited:return
        visited.add(id(c))
        attrs.update(i.argval for i in dis.get_instructions(func) if i.opname=='LOAD_ATTR')
        if 'getattr' in c.co_names:
            attrs.update(x for x in c.co_consts if isinstance(x,str))
        for called in c.co_names:
            child=ns.get(called)
            if getattr(child,'__code__',None) is not None:visit(child)
    if code:visit(f)
    allowed=('url','method','params','body','path_params','profile','skill_id','request_identity','timeout','dry_run','yes','shop_name','no_browser')
    return {'callable':callable(f),'argcount':code.co_argcount if code else 0,'attrs_read':sorted(attrs.intersection(allowed))}
f=inspect_function('cmd_invoke')
print(json.dumps({'host':'%d.%d.%d'%sys.version_info[:3],'cmd_invoke':f['callable'],'argcount':f['argcount'],'attrs_read':f['attrs_read'],'login':inspect_function('cmd_login')}))
"""


def needs_bridge(body_text):
    return len(str(body_text or '').encode('utf-16-le'))//2>COMMAND_LINE_BODY_LIMIT


def runtime_sha(data):return hashlib.sha256(data).hexdigest()


def _run(command,**kwargs):
    return subprocess.run([str(x) for x in command],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0,**kwargs)


def probe_runtime(runtime_path,runtime_bytes,*,python,cache,login=False):
    digest=runtime_sha(runtime_bytes);cache=Path(cache);runtime_path=Path(runtime_path)
    contract={'attrs':list(NEEDED_ATTRIBUTES),'loginAttrs':list(LOGIN_ATTRIBUTES),'engine':3}
    known={}
    if cache.is_file():
        try:
            known=json.loads(cache.read_text(encoding='utf-8'))
            if not isinstance(known,dict):known={}
        except (OSError,ValueError):pass
    cached=known.get(digest,{})
    # Recheck the requested contract when replaying evidence; failed child launches aren't cached.
    if cached.get('contract')==contract and cached.get('ok') and (not login or cached.get('loginOk')):
        runtime_path.parent.mkdir(parents=True,exist_ok=True)
        if not runtime_path.exists() or runtime_path.read_bytes()!=runtime_bytes:runtime_path.write_bytes(runtime_bytes)
        return {**cached,'sha256':digest,'cached':True}
    runtime_path.parent.mkdir(parents=True,exist_ok=True);runtime_path.write_bytes(runtime_bytes)
    data=None
    try:
        proc=_run([python,'-X','utf8','-c',_PROBE_SOURCE,runtime_path],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
        if proc.returncode==0:data=json.loads(proc.stdout.strip().splitlines()[-1])
    except (OSError,ValueError,subprocess.SubprocessError,IndexError):pass
    data=data if isinstance(data,dict) else {}
    host=str(data.get('host',''));invocation_ok=bool(data.get('cmd_invoke') and data.get('argcount')==1 and host.startswith('3.12.') and set(NEEDED_ATTRIBUTES).issubset(data.get('attrs_read') or []))
    login_data=data.get('login') or {};login_ok=bool(login_data.get('callable') and set(LOGIN_ATTRIBUTES).issubset(login_data.get('attrs_read') or []))
    ok=invocation_ok and (not login or login_ok)
    result={'ok':ok,'invokeOk':invocation_ok,'loginOk':login_ok,'host':host,'attrsRead':data.get('attrs_read') or [],'loginAttrsRead':login_data.get('attrs_read') or [],'contract':contract,'userMessage':'' if ok else interface_changed_message()}
    if invocation_ok:
        known[digest]={**result,'ok':True}
        try:
            cache.parent.mkdir(parents=True,exist_ok=True)
            tmp=cache.with_suffix('.incoming');tmp.write_text(json.dumps(known,ensure_ascii=False),encoding='utf-8');tmp.replace(cache)
        except OSError:pass
    return {**result,'sha256':digest,'cached':False}


def interface_changed_message():
    return ('这个版本的京麦 CLI 改变了大请求的发送方式，目前不能用它处理属性补全、素材绑定、整版编辑这类大请求。'
            '查询、审计、授权、本地生成、短标题导入、批量抠图不受影响。下一步：不要升级或回退 CLI，把这条提示发给 Skill 维护人适配后再继续。')


def host_version(python):
    try:
        out=_run([python,'-c','import sys;print(sys.version_info[0],sys.version_info[1])'],capture_output=True,text=True,timeout=20)
        if out.returncode==0:return tuple(int(x) for x in out.stdout.split()[:2])
    except (OSError,ValueError,subprocess.SubprocessError):pass
    return None


def _launcher_candidates():
    found=[sys.executable,shutil.which('python3.12')]
    try:
        out=_run(['py','-3.12','-c','import sys;print(sys.executable)'],capture_output=True,text=True,timeout=20)
        if out.returncode==0 and out.stdout.strip():found.append(out.stdout.strip())
    except (OSError,subprocess.SubprocessError):pass
    return [x for x in found if x]


def find_bridge_python(*,env=None,home=None,extra=None):
    env=os.environ if env is None else env;home=Path(home or env.get('USERPROFILE') or Path.home())
    candidates=[]
    if env.get('JDO_PYTHON312'):
        configured=Path(env['JDO_PYTHON312'])
        return configured if configured.is_file() and host_version(configured)==(3,12) else None
    candidates.append(home/'AppData/Local/Programs/Python/Python312/python.exe')
    candidates.extend(Path(x) for x in (extra if extra is not None else _launcher_candidates()) if x)
    for path in dict.fromkeys(candidates):
        if path.is_file() and host_version(path)==(3,12):return path
    return None


def bridge_status(*,exe,python,runtime_ok):
    available=bool(exe and python and runtime_ok and runtime_ok.get('ok'))
    if available:return {'available':True,'affected':[],'unaffected':UNAFFECTED,'userMessage':''}
    if not exe:step='先用“京麦 CLI 店铺连接”安装官方京麦 CLI。'
    elif not python:step='让助手帮你安装 Python 3.12；公司电脑如果拦截安装，请联系 IT 放行，或转给 Skill 维护人。'
    else:step='当前京麦 CLI 改变了大请求的发送方式，请转给 Skill 维护人适配，不要自行升级或回退。'
    return {'available':False,'affected':AFFECTED,'unaffected':UNAFFECTED,
            'userMessage':'受影响的是：属性补全、素材绑定、整版编辑这类大请求。\n不受影响的是：查询、审计、授权、本地生成、短标题导入、批量抠图。\n下一步：'+step}
