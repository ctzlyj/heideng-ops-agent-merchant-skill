"""Masked merchant input only on approved image execution; no business scheduler."""
from __future__ import annotations
import hmac, json, os, secrets, threading, time
from pathlib import Path
from .safety import SafetyError
from .state import merchant_home
from .merchant_key_store import read_key, store_key


class KeyInputSession:
    def __init__(self, port):
        self.origin=f'http://127.0.0.1:{port}';self.host=f'127.0.0.1:{port}'
        self.csrf=secrets.token_urlsafe(32);self.value=None;self.remember=False;self.done=threading.Event()
    def accept(self, host, origin, csrf, value, remember):
        if host!=self.host or origin!=self.origin or not hmac.compare_digest(str(csrf),self.csrf) or self.done.is_set():raise SafetyError('merchant-key-input-request-refused')
        if not isinstance(value,str) or len(value.encode())>8192:raise SafetyError('merchant-key-input-invalid')
        self.value=value.strip() or None;self.remember=remember is True;self.done.set()


def _prompt_local_page(timeout=300):
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import parse_qs, urlsplit
    import webbrowser
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(5)
        def log_message(self,*args):pass  # No request URL, body, token or key in logs.
        def respond(self,status,body):
            self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(body.encode())
        def do_GET(self):
            parsed=urlsplit(self.path)
            valid_query=not parsed.query or parse_qs(parsed.query).get('session')==[session.csrf]
            if self.headers.get('Host')!=session.host or parsed.path!='/' or not valid_query or session.done.is_set():self.respond(403,'请求无效');return
            self.respond(200,f"""<!doctype html><meta charset=utf-8><title>黑灯商家安全输入</title>
<h2>输入商家自己的 LTS4AI Key</h2><p>仅用于已确认范围和费用的生图任务。不读公司凭据，不粘贴到聊天。</p>
<form method=post action=/key><input type=hidden name=csrf value='{session.csrf}'>
<input type=password name=key autocomplete=off maxlength=8192 required autofocus>
<p><label><input type=checkbox name=remember value=yes>在本机系统安全存储中记住（非明文）</label></p>
<button type=submit>用于本次任务</button></form><p>关闭此页面或等待超时可取消。</p>""")
        def do_POST(self):
            try:
                if self.path!='/key' or self.headers.get('Content-Type','').split(';')[0]!='application/x-www-form-urlencoded':raise SafetyError('merchant-key-input-request-refused')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16384:raise SafetyError('merchant-key-input-request-refused')
                data=parse_qs(self.rfile.read(length).decode('utf-8'),keep_blank_values=True)
                if any(len(v)!=1 for v in data.values()):raise SafetyError('merchant-key-input-request-refused')
                session.accept(self.headers.get('Host'),self.headers.get('Origin'),data.get('csrf',[''])[0],data.get('key',[''])[0],data.get('remember')==['yes'])
                self.respond(200,'已接收。本页不显示或保存Key，可关闭页面。')
            except (SafetyError,ValueError,UnicodeError):self.respond(403,'请求无效')
    server=HTTPServer(('127.0.0.1',0),Handler);server.timeout=0.25
    session=KeyInputSession(server.server_port)
    try:
        url=session.origin+'/'
        print(json.dumps({'status':'awaiting_key_input','keyInputUrl':url,'businessExecuted':False,'message':'请在打开的页面输入商家自己的Key；若页面未自动打开，请复制此本机地址。'},ensure_ascii=False),flush=True)
        webbrowser.open(url,new=2)
        deadline=time.monotonic()+timeout
        while not session.done.is_set() and time.monotonic()<deadline:server.handle_request()
        return session.value,session.remember
    finally:server.server_close()


def prompt_key(state=None):
    state=Path(state or merchant_home())
    try:
        import tkinter as tk
        from tkinter import simpledialog, messagebox
        root=tk.Tk();root.withdraw()
    except Exception:
        value,remember=_prompt_local_page()
    else:
        try:
            value=simpledialog.askstring('商家 LTS4AI Key','输入商家自己的Key。本次费用与范围应已确认；取消不执行任务。',show='*',parent=root)
            remember=bool(value) and messagebox.askyesno('系统安全存储','是否在本机系统安全存储中记住Key，避免每次重复输入？不会写明文Key文件。',parent=root)
        finally:root.destroy()
    if value and remember:
        try:store_key(state,value.strip())
        except SafetyError:
            print(json.dumps({'notice':'merchant-secure-storage-unavailable','keyUsage':'this-process-only','nextAction':'系统安全存储不可用；本次仍仅在进程内使用，不保存明文。'},ensure_ascii=False))
    return value


def with_key(action, *, state=None, preflight=None):
    state=Path(state or merchant_home())
    if preflight:preflight()  # No key prompt if interpreter/dependencies/bridge not usable.
    name='HEIDENG_MERCHANT_LTS4AI_API_KEY';previous=os.environ.get(name)
    try:value=previous or read_key(state)
    except SafetyError:value=None  # User can replace a no-longer-accessible OS secret via masked input.
    if not value:value=prompt_key(state)
    if value is None or not value.strip():
        print(json.dumps({'status':'cancelled','businessExecuted':False}));return 2
    try:
        os.environ[name]=value.strip()
        return action()
    finally:
        if previous is None:os.environ.pop(name,None)
        else:os.environ[name]=previous
        value=None
