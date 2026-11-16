"""Agent interface: dispatch actual mature Skills, not rebuilt business operations."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from . import VERSION, SKILL_NAME
from .state import merchant_home
from .safety import SafetyError
from .mature_runtime import ROUTES, MatureSourceUnavailable, run, status

def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description='黑灯商家版：复用成熟业务 Skill')
    parser.add_argument('--state', type=Path, default=None)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    p = sub.add_parser('run')
    p.add_argument('--entry', help='registered source entry only')
    p.add_argument('capability', choices=sorted(ROUTES))
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == 'status':
            print(json.dumps({'skill': SKILL_NAME, 'version': VERSION, **status()}, ensure_ascii=False))
            return 0
        return run(args.capability, args.arguments, state=args.state or merchant_home(), entry=args.entry)
    except MatureSourceUnavailable as error:
        print(json.dumps({'status': 'blocked', 'error': str(error), 'capability': error.capability, 'builtinFallback': False}, ensure_ascii=False))
        return 2
    except SafetyError as error:
        print(json.dumps({'status':'blocked', 'error': str(error)}, ensure_ascii=False))
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
