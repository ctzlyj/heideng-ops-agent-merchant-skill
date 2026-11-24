"""Entry point kept inside the single installed Skill."""
import json, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
if __name__=='__main__' and sys.platform=='darwin':
    for entry in (root/'heideng_merchant', root/'heideng_merchant/__init__.py'):
        if getattr(entry.stat(),'st_flags',0) & 0x40000000:
            print(json.dumps({'status':'blocked','error':'macos-cloud-file-not-local','path':str(entry),'nextAction':'在访达中选择“现在下载”，下载后从原任务继续。'},ensure_ascii=False))
            raise SystemExit(2)
from heideng_merchant import CloudFileUnavailable, check_entry_modules

def main(argv=None):
    try:
        check_entry_modules(root,('cli','safety','state','mature_runtime','runtime_dependencies','official','distribution'))
        from heideng_merchant.cli import main as run
        return run(argv)
    except CloudFileUnavailable as error:
        print(json.dumps(error.receipt(),ensure_ascii=False))
        return 2

if __name__=='__main__':raise SystemExit(main())
