"""Agent interface: dispatch actual mature Skills, not rebuilt business operations."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from . import VERSION, SKILL_NAME
from .state import merchant_home
from .safety import SafetyError, redact
from .mature_runtime import ROUTES, MatureSourceUnavailable, run, status

def build_parser():
    parser = argparse.ArgumentParser(description='黑灯商家版：复用成熟业务 Skill')
    parser.add_argument('--state', type=Path, default=None)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    k=sub.add_parser('key',help='merchant OS secret maintenance, never prints a key')
    k.add_argument('action',choices=('forget',))
    u = sub.add_parser('update', help='software maintenance only; never business scheduling')
    us = u.add_subparsers(dest='update_command', required=True)
    for name in ('status','check','apply','enable','disable','recover','repair-switch'): us.add_parser(name)
    v = us.add_parser('usage'); v.add_argument('action', choices=('begin','heartbeat','end')); v.add_argument('--task-id',required=True); v.add_argument('--component',action='append'); v.add_argument('--receipt'); v.add_argument('--loaded-version')
    p = sub.add_parser('run')
    p.add_argument('--entry', help='registered source entry only')
    p.add_argument('capability', choices=sorted(ROUTES))
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        state = args.state or merchant_home()
        if args.command == 'key':
            from .merchant_key_store import forget_key
            forget_key(state)
            print(json.dumps({'status':'forgotten','merchantKeyOnly':True,'businessExecuted':False}));return 0
        if args.command == 'update':
            from .runtime_dependencies import reexec_update_runtime
            switched=reexec_update_runtime(state)
            if switched is not None:return switched
            from . import update_client as updater
            name = args.update_command
            if name == 'status': result = updater.status(state)
            elif name == 'check': result = updater.check(state, force=True)
            elif name == 'apply': result = updater.apply(state)
            elif name == 'enable':
                result = updater.set_enabled(state, True); updater.maybe_schedule(state)
            elif name == 'disable': result = updater.set_enabled(state, False)
            elif name == 'recover': result = updater.recover(state, confirm=True)
            elif name == 'repair-switch': result = updater.recover_switch(state)
            else:
                result = updater.usage(state, args.action, args.task_id, components=args.component, receipt=args.receipt, loaded_version=args.loaded_version)
                if args.action == 'end': updater.maybe_schedule(state)
            print(json.dumps(redact(result), ensure_ascii=False)); return 0
        if args.command == 'status':
            from .update_client import consume_notice
            try: notice = consume_notice(state)
            except Exception: notice = {'reason':'update-status-unavailable','businessUsable':True,'action':'diagnose-updater-settings-without-resetting-trust'}
            print(json.dumps({'skill': SKILL_NAME, 'version': VERSION, **status(), 'softwareUpdateNotice': notice}, ensure_ascii=False))
            return 0
        return run(args.capability, args.arguments, state=args.state or merchant_home(), entry=args.entry)
    except MatureSourceUnavailable as error:
        print(json.dumps({'status': 'blocked', 'error': str(error), 'capability': error.capability, 'builtinFallback': False}, ensure_ascii=False))
        return 2
    except SafetyError as error:
        print(json.dumps({'status':'blocked', 'error': str(error)}, ensure_ascii=False))
        return 2

    finally:
        if args.command != 'update':
            try:
                from .update_client import maybe_schedule
                maybe_schedule(args.state or merchant_home())
            except Exception: pass

if __name__ == '__main__':
    raise SystemExit(main())
