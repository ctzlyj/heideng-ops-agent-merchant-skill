#!/usr/bin/env python3
"""File-body execution of the official CLI, after the shared interface check."""
from __future__ import annotations
import argparse
import json
import marshal
import sys
from pathlib import Path
import jdo_bridge_probe as bp

class OfficialDefaults(argparse.Namespace):
    # Unspecified official optional arguments remain None; no local account retrieval.
    def __getattr__(self,name):return None


def build_invoke_args(request):
    profile=str(request.get('profile') or '').strip()
    if not profile or profile.casefold()=='default':
        raise ValueError('请指定该店独立 Profile，不能使用 default。')
    return OfficialDefaults(url=request['url'],method=request.get('method','POST'),
        params=json.dumps(request.get('params',{}),ensure_ascii=False,separators=(',',':')),
        body=Path(request['bodyFile']).read_text(encoding='utf-8'),path_params=request.get('pathParams'),
        profile=profile,skill_id=request.get('skillId'),request_identity=request.get('requestIdentity','vender'),
        account_identity=None,jos_pin=None,extra_headers=None,
        timeout=request.get('timeout',180),dry_run=bool(request.get('dryRun',False)),yes=bool(request.get('yes',False)))


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--request',type=Path);parser.add_argument('--probe',action='store_true')
    args=parser.parse_args()
    if sys.version_info[:2]!=(3,12):raise RuntimeError(bp.bridge_status(exe=True,python=None,runtime_ok=None)['userMessage'])
    runtime=args.runtime.read_bytes()
    checked=bp.probe_runtime(args.runtime,runtime,python=sys.executable,cache=args.runtime.parent/'interface-cache.json')
    if not checked['ok']:raise RuntimeError(checked['userMessage'])
    if args.probe:
        print(json.dumps({'status':'ready','invokePerformed':False},ensure_ascii=False));return 0
    if args.request is None:parser.error('--request is required unless --probe is selected')
    request=json.loads(args.request.read_text(encoding='utf-8'));invoke_args=build_invoke_args(request)
    namespace={'__name__':'jdo_cli_embedded','__file__':'jdo-cli.py'}
    exec(marshal.loads(runtime),namespace)
    namespace['cmd_invoke'](invoke_args)
    return 0

if __name__=='__main__':raise SystemExit(main())
