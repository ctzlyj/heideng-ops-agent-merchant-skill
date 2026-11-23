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


def _prompt_local_page(timeout=300, *, beta=False):
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
<h2>{'验证黑灯内测资格' if beta else '输入商家自己的 LTS4AI Key'}</h2><p>{'请填写运营方分配给本商家的 LTS4AI 专用 Key，验证通过后保存在本机系统安全存储。' if beta else '仅用于已确认范围和费用的生图任务。不读公司凭据，不粘贴到聊天。'}</p>
<form method=post action=/key><input type=hidden name=csrf value='{session.csrf}'>
<input type=password name=key autocomplete=off maxlength=8192 required autofocus>
<p>提交后，Key 将保存到本机系统安全存储。</p>
<button type=submit>{'验证资格' if beta else '用于本次任务'}</button></form><p>关闭此页面或等待超时可取消。</p>""")
        def do_POST(self):
            try:
                if self.path!='/key' or self.headers.get('Content-Type','').split(';')[0]!='application/x-www-form-urlencoded':raise SafetyError('merchant-key-input-request-refused')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16384:raise SafetyError('merchant-key-input-request-refused')
                data=parse_qs(self.rfile.read(length).decode('utf-8'),keep_blank_values=True)
                if any(len(v)!=1 for v in data.values()):raise SafetyError('merchant-key-input-request-refused')
                session.accept(self.headers.get('Host'),self.headers.get('Origin'),data.get('csrf',[''])[0],data.get('key',[''])[0],True)
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


def _prompt_native_window(timeout=300, on_visible=None, *, beta=False):
    import tkinter as tk
    from tkinter import font, ttk

    root = tk.Tk()
    try:
        root.withdraw()
        root.title('黑灯商家内测 · 资格验证' if beta else '黑灯生图 · 安全输入')
        root.resizable(False, False)
        background = '#f6f8fc'
        root.configure(background=background)
        body_font = font.nametofont('TkDefaultFont', root=root)
        title_font = body_font.copy()
        title_font.configure(size=17, weight='bold')
        frame = tk.Frame(root, background=background, padx=26, pady=23)
        frame.pack(fill='both', expand=True)
        tk.Label(frame, text='验证内测资格' if beta else '输入生图密钥', font=title_font, background=background,
                 foreground='#18243a').pack(anchor='w')
        tk.Label(frame, text='请输入运营方分配给本商家的 LTS4AI 专用 Key。' if beta else '用你的 LTS4AI Key 继续已确认的商品生图。',
                 background=background, foreground='#44516a').pack(anchor='w', pady=(8, 18))
        tk.Label(frame, text='LTS4AI API Key', background=background, foreground='#18243a').pack(anchor='w')
        entry = ttk.Entry(frame, width=44, show='●')
        entry.pack(fill='x', ipady=5, pady=(6, 2))
        error = tk.StringVar(root)
        tk.Label(frame, textvariable=error, background=background, foreground='#a22929').pack(anchor='w')
        tk.Label(frame, text='提交后，Key 将保存到本机系统安全存储。',
                 background=background, foreground='#44516a').pack(anchor='w', pady=(4, 16))
        result = (None, False)

        def cancel(_event=None):
            entry.delete(0, tk.END)
            root.quit()

        def submit(_event=None):
            nonlocal result
            candidate = entry.get().strip()
            if not candidate or len(candidate.encode('utf-8')) > 8192:
                error.set('请输入有效的 LTS4AI Key。')
                entry.focus_set()
                return
            result = (candidate, True)
            cancel()

        buttons = tk.Frame(frame, background=background)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='验证资格' if beta else '继续生图', command=submit).pack(side='right')
        ttk.Button(buttons, text='取消', command=cancel).pack(side='right', padx=(0, 8))
        root.bind('<Return>', submit)
        root.bind('<Escape>', cancel)
        root.protocol('WM_DELETE_WINDOW', cancel)
        root.update_idletasks()
        x = max(0, (root.winfo_screenwidth() - root.winfo_reqwidth()) // 2)
        y = max(0, (root.winfo_screenheight() - root.winfo_reqheight()) // 2)
        root.geometry(f'+{x}+{y}')
        root.attributes('-topmost', True)
        root.deiconify()
        root.lift()
        root.after_idle(entry.focus_force)
        root.after(1800, lambda: root.attributes('-topmost', False))
        root.after(int(timeout * 1000), cancel)
        root.update_idletasks()
        if on_visible:
            on_visible()
        root.mainloop()
        return result
    finally:
        root.destroy()


def prompt_key(state=None):
    state = Path(state or merchant_home())
    try:
        import tkinter as tk
    except ImportError:
        value, remember = _prompt_local_page()
    else:
        try:
            value, remember = _prompt_native_window(on_visible=lambda: print(json.dumps(
                {'status': 'awaiting_key_input', 'inputSurface': 'native-window', 'businessExecuted': False}),
                flush=True))
        except tk.TclError:
            value, remember = _prompt_local_page()
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
