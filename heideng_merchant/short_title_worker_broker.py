"""Local command admission only; native actions remain on the owning main thread."""
import json,queue,re,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .operations import digest
from .safety import SafetyError,redact
from . import short_title_worker_state as original

MAX_BODY=4096

def allowed_request(method,path,headers,port,worker_id,fingerprint):
 if type(port) is not int or not 1024<=port<=65535 or not isinstance(worker_id,str) or original.ID.fullmatch(worker_id) is None or not isinstance(fingerprint,str) or original.HASH.fullmatch(fingerprint) is None:return False
 if any(not isinstance(k,str) or not isinstance(v,str) for k,v in headers.items()):return False
 h={k.lower():v for k,v in headers.items()}
 if h.get('host')!='127.0.0.1:'+str(port) or h.get('x-heideng-local')!='1' or h.get('x-heideng-worker')!=worker_id or h.get('x-heideng-fingerprint')!=fingerprint or any(k in h for k in ('origin','referer','transfer-encoding')) or h.get('sec-fetch-site','none')!='none':return False
 return method=='POST' and path=='/commands' or method=='GET' and (path=='/status' or re.fullmatch(r'/command-status/[a-f0-9]{32}',path) is not None)

def parse_command(raw,length):
 if not isinstance(raw,bytes) or type(length) is not int or not 0<length<=MAX_BODY or len(raw)!=length:raise SafetyError('bounded-complete-worker-command-required')
 def unique(pairs):
  out={}
  for k,v in pairs:
   if k in out:raise SafetyError('unique-worker-command-keys-required')
   out[k]=v
  return out
 try:value=json.loads(raw.decode('utf-8'),object_pairs_hook=unique,parse_constant=lambda value:(_ for _ in ()).throw(SafetyError('finite-worker-command-required')))
 except (ValueError,UnicodeError,RecursionError):raise SafetyError('worker-command-json-required') from None
 if not isinstance(value,dict) or set(value)!={'requestId','action','importId','fingerprint','confirmed','ttl'} or redact(value)!=value:raise SafetyError('exact-public-worker-command-required')
 return value

class CommandBroker:
 def __init__(self,state,job,run):
  self.state=state;self.job=job;self.run=run;self.lock=threading.RLock();self.queue=queue.Queue();self.max_pending=32;self.accepting=True;self.stop_requested=threading.Event()
  self.seen={rid:digest(value) for rid,value in original._entries(state,original.COMMAND_FOLDERS[0],job,original.REQ).items()}
  for rid in self.seen:original.command_status(state,job,rid)
  self.snapshot={'workerId':job['workerId'],'workerFingerprint':job['fingerprint'],'runId':run['runId'],'stage':'starting','ready':False}
 def update(self,value,*,stage=None,ready=None):
  with self.lock:
   out=original.public_result(value)
   self.snapshot.update(out)
   if stage is not None:
    if not isinstance(stage,str) or len(stage)>128 or redact(stage)!=stage:raise SafetyError('public-worker-stage-required')
    self.snapshot['stage']=stage
   if ready is not None:
    if type(ready) is not bool:raise SafetyError('worker-ready-boolean-required')
    self.snapshot['ready']=ready
 def status(self):
  with self.lock:return dict(self.snapshot)
 def pending_count(self):return self.queue.qsize()
 def take(self):
  try:return self.queue.get_nowait()
  except queue.Empty:return None
 def freeze(self):
  with self.lock:self.accepting=False
 def submit(self,command):
  with self.lock:
   if not self.accepting:raise SafetyError('worker-closing-no-new-command-admission')
   original._check_command(self.state,self.job,self.run,command)
   rid=command['requestId'];path=original.file(self.state,original.COMMAND_FOLDERS[0],self.job['workerId'],rid);old=original._read(path)
   if rid in self.seen and (old is None or digest(old)!=self.seen[rid]):raise SafetyError('original-worker-command-lost-or-changed')
   if old is not None:
    if old['command']!=command:raise SafetyError('original-worker-request-id-content-changed')
    return original.command_status(self.state,self.job,rid)
   if self.pending_count()>=self.max_pending:raise SafetyError('worker-command-queue-full-no-admission')
   accepted=original.accept_command(self.state,self.job,self.run,command);self.seen[rid]=digest(accepted);self.queue.put_nowait(accepted)
   if command['action']=='stop':self.stop_requested.set()
   return original.command_status(self.state,self.job,rid)

def make_server(broker):
 class Handler(BaseHTTPRequestHandler):
  def setup(self):
   super().setup();self.connection.settimeout(2)
  def log_message(self,*args):pass
  def send_public(self,value,code=200):
   raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
   if len(raw)>64*1024:raw=b'{"status":"bounded-response-required"}';code=500
   self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
   try:self.wfile.write(raw)
   except (OSError,TimeoutError):pass
  def serve(self):
   critical=('Host','Content-Length','Content-Type','X-Heideng-Local','X-Heideng-Worker','X-Heideng-Fingerprint')
   if any(len(self.headers.get_all(k,[]))>1 for k in critical) or not allowed_request(self.command,self.path,dict(self.headers.items()),self.server.server_port,broker.job['workerId'],broker.job['fingerprint']):self.send_public({'status':'request-refused'},403);return
   try:
    if self.command=='GET':
     if self.headers.get('Content-Length','0')!='0':raise SafetyError('empty-worker-read-required')
     result=broker.status() if self.path=='/status' else original.command_status(broker.state,broker.job,self.path.rsplit('/',1)[-1])
    else:
     length=self.headers.get('Content-Length','');content=self.headers.get('Content-Type','').lower()
     if not re.fullmatch(r'[1-9][0-9]{0,3}',length) or int(length)>MAX_BODY or content not in ('application/json','application/json; charset=utf-8'):raise SafetyError('bounded-worker-json-body-required')
     result=broker.submit(parse_command(self.rfile.read(int(length)),int(length)))
    self.send_public(result)
   except Exception:self.send_public({'status':'original-command-state-required-no-replay'},400)
  do_GET=do_POST=serve
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;return server
