"""Transient masked input, for an already user-approved image task; no disk storage."""
import json, os
from .safety import SafetyError

def prompt_key():
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        try:
            return simpledialog.askstring('商家 LTS4AI Key', '输入商家自己的 LTS4AI Key。本次任务进程内使用，不保存到文件，也不读取公司或个人 Skill 凭据。费用与范围应已由 Agent 与你确认。取消不会执行任务。', show='*', parent=root)
        finally:
            root.destroy()
    except Exception:
        raise SafetyError('merchant-secure-key-dialog-unavailable') from None

def with_key(action):
    value = prompt_key()
    if value is None or not value.strip():
        print(json.dumps({'status': 'cancelled', 'businessExecuted': False}))
        return 2
    name = 'HEIDENG_MERCHANT_LTS4AI_API_KEY'
    previous = os.environ.get(name)
    try:
        os.environ[name] = value.strip()
        return action()
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous
        value = None
