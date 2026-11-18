"""Host launches only for user-approved images; preflight then secure merchant input."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.cli import main,build_parser
from heideng_merchant.mature_runtime import preflight
from heideng_merchant.merchant_key_ui import with_key
from heideng_merchant.safety import SafetyError
from heideng_merchant.state import merchant_home,FileLock

def entry(argv=None):
    argv=sys.argv[1:] if argv is None else argv
    args=build_parser().parse_args(argv)
    if args.command!='run' or any(x in ('--help','-h','help') for x in args.arguments):return main(argv)
    arguments=list(args.arguments)
    if arguments[:1]==['--']:arguments=arguments[1:]
    if args.capability=='materials' and arguments[:1]==['repair-rejected'] and ('--paid-generation' not in arguments or '--no-paid-generation' in arguments):
        return main(argv)  # Free repair must not read/prompt a Key merely because this wrapper was selected.
    state=args.state or merchant_home()
    from heideng_merchant.runtime_dependencies import ensure_core
    ensure_core(state,Path(__file__).resolve().parents[1])
    # Prevent disk replacement while input/preflight uses this version. No host restart.
    with FileLock(state/'install.lock',shared=True):
        return with_key(lambda:main(argv),state=state,preflight=lambda:preflight(args.capability,args.arguments,state=state,entry=args.entry))

if __name__=='__main__':
    try:raise SystemExit(entry())
    except SafetyError as error:
        print(json.dumps({'status':'blocked','error':str(error),'businessExecuted':False}));raise SystemExit(2)
