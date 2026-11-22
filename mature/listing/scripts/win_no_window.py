"""给批量脚本用的子进程静默包装：调用 jdo-cli 等 CLI 时不弹控制台窗口。

用法（在脚本 import jdo_listing_mvp 之前）：

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import win_no_window  # noqa: F401

Windows 下会给 subprocess.run/Popen/call/check_output 统一追加
CREATE_NO_WINDOW 与 STARTF_USESHOWWINDOW/SW_HIDE，避免逐条命令闪黑框。
"""

import subprocess
import sys

def _hidden_kwargs(kwargs):
    if sys.platform == "win32":
        kwargs["creationflags"] = (kwargs.get("creationflags") or 0) | subprocess.CREATE_NO_WINDOW
        startup = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startup
    return kwargs


# Standard run/check_output also use Popen. Preserve their exit-code and timeout handling.
if sys.platform == "win32" and not getattr(subprocess.Popen, "_merchant_hidden", False):
    class Popen(subprocess.Popen):
        _merchant_hidden = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **_hidden_kwargs(kwargs))

    subprocess.Popen = Popen

run = subprocess.run
Popen = subprocess.Popen
