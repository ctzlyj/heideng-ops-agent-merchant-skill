"""First-run self-check: verify dependencies and give actionable next steps for non-technical users."""
from __future__ import annotations
import sys as _help_sys
if '--help' in _help_sys.argv:
    print('self_check.py --root <output> [original parameters]; dispatcher supplies isolated state')
    raise SystemExit(0)
import os, shutil, subprocess, sys
from pathlib import Path

def check_python():
    ok = sys.version_info >= (3, 10)
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return ok, f"Python {ver}", "" if ok else "安装 Python 3.10+：https://www.python.org/downloads/"

def check_node():
    node = shutil.which("node")
    if not node: return False, "未找到", "安装 Node.js 24+：https://nodejs.org/ 或联系 IT"
    try:
        ver = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=15).stdout.strip()
        major = int(ver.lstrip("v").split(".")[0])
        return (major >= 24), f"Node {ver}", "" if major >= 24 else f"升级到 Node 24+，当前 {ver}"
    except Exception: return False, "检测失败", "确认 node --version 可正常执行"

def check_python_deps():
    missing = []
    for mod, pip in [("openpyxl","openpyxl"),("PIL","Pillow"),("requests","requests")]:
        try: __import__(mod)
        except ImportError: missing.append(pip)
    if missing: return False, f"缺少: {', '.join(missing)}", f"运行: pip install {' '.join(missing)}"
    return True, "openpyxl, Pillow, requests 已安装", ""

def check_webcli():
    """Legacy function name; the merchant package uses its owned transport, not employee tools."""
    stage=os.environ.get('HEIDENG_COLLECTION_STATE_DIR')
    if not stage:return False, '商家采集状态目录未绑定', '由Agent传入原 --root/--state-dir，准备实际任务浏览器'
    context=Path(stage)/'browser_context.json'
    if not context.is_file():return False, '任务浏览器尚未配置', 'Agent从实际拥有的会话记录配置，不复制工作浏览器或Cookie'
    return True, '任务配置存在（不等于真实登录/平台权限已验证）', ''

def check_output_dir():
    value=os.environ.get('HEIDENG_COLLECTION_ROOT')
    if not value:return False,'输出目录未指定','Agent传 --root=<目录>'
    target=Path(value).resolve()
    try:
        target.mkdir(parents=True,exist_ok=True)
        return os.access(target,os.W_OK), '商家任务输出目录可写', ''
    except OSError:return False,'输出目录不可写','检查本次目录权限，不换店铺或授权'

def main():
    checks = [("Python 3.10+", check_python),("Node.js 24+", check_node),("Python 依赖", check_python_deps),
              ("商家任务浏览器传输", check_webcli),("输出目录权限", check_output_dir)]
    all_ok = True
    print("=== jd-hot-link-collector 自检 ===\n")
    for name, fn in checks:
        ok, detail, fix = fn()
        print(f"  {'✓' if ok else '✗'} {name}: {detail}")
        if not ok:
            all_ok = False
            if fix: print(f"    → 下一步: {fix}")
    print()
    if all_ok:
        print("全部通过！把商品清单 Excel 发给 JoyCode，说「用 jd-hot-link-collector 采集」即可。")
    else:
        print("有缺项，按上面「下一步」处理后重新运行: python -X utf8 scripts/self_check.py")
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
