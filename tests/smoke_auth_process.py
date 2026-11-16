"""Optional real-loopback/cross-process smoke; synthetic shops only, no merchant API calls."""
import argparse,json,subprocess,sys,tempfile,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.auth_manager import AuthManager,broker_request
from heideng_merchant.auth_broker import BrokerState,make_server
from heideng_merchant.safety import atomic_json,read_json,clean_environment
from tests.test_auth_flow import FakeClient,FakeBrowser

class Client(FakeClient):
 def ready(self):return True
 def identity(self,profile):return {'shopName':'process-test-shop','venderId':'1','shopId':'9','shopType':'POP'}
 def login_process(self,*args):
  process=super().login_process(*args);process.returncode=0;return process
class Browser(FakeBrowser):
 def __init__(self,shop_name,vender_id=None):super().__init__({'shopName':shop_name,'venderId':'1','source':'https://jingmai.jd.com/identity'})
class Runtime:
 def ensure(self):return {'status':'ready'}
 def python(self):return Path(sys.executable)

p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');p.add_argument('--contender',action='store_true');p.add_argument('--state');p.add_argument('--job');args=p.parse_args()
if args.worker:
 from heideng_merchant import auth_worker
 auth_worker.OfficialClient=lambda state:Client();auth_worker.HostControllerBrowser=lambda state,job,shop,controller,**kw:Browser(shop,kw.get("vender_id"))
 auth_worker.run_worker(Path(args.state),args.job)
 raise SystemExit(0)
if args.contender:
 def forbidden(*a,**k):raise AssertionError('a second auth worker must not be launched')
 m=AuthManager(Path(args.state),runtime=Runtime(),client=Client(),starter=forbidden,startup_wait=0)
 r=m.start('process-test-shop',foreground=True,vender_id='1');print(json.dumps({'taskId':r['taskId']}));raise SystemExit(0)

owned=[]
with tempfile.TemporaryDirectory(prefix='merchant-auth-smoke-') as d:
 state=Path(d)
 def start(command,**options):
  command[2]=str(Path(__file__).resolve());command.insert(3,'--worker')
  process=subprocess.Popen(command,**options);owned.append(process);return process
 m=AuthManager(state,runtime=Runtime(),client=Client(),starter=start,startup_wait=10,browser_controller=["python","synthetic-controller.py"])
 try:
  first=m.start('process-test-shop',foreground=True,vender_id='1')
  contenders=[subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'--contender','--state',str(state)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=clean_environment(state)) for _ in range(2)]
  for child in contenders:
   output,error=child.communicate(timeout=15)
   assert child.returncode==0 and json.loads(output)['taskId']==first['taskId']
  deadline=time.monotonic()+10
  while time.monotonic()<deadline:
   status=m.status(first['taskId'])
   if status['status']!='running':break
   time.sleep(.1)
  assert status['ready'] and len(owned)==1
  assert read_json(state/'shops.json')[first['profile']]['venderId']=='1'
  for process in owned:assert process.wait(timeout=10)==0
 finally:
  for process in owned:
   if process.poll() is None:process.terminate();process.wait(timeout=5)

state=BrokerState();state.update({'taskId':'a'*24,'stage':'waiting_login','ready':False},{'browserStage':'jingmai-login'})
server=make_server(state);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
 assert broker_request(server.server_port,'/status','a'*24)['taskId']=='a'*24
 assert broker_request(server.server_port,'/observe','a'*24)['observation']['browserStage']=='jingmai-login'
 import urllib.request,urllib.error
 req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/cancel',data=b'',headers={'Origin':'https://attacker.example','X-Heideng-Local':'1','X-Heideng-Task':'a'*24})
 try:urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req);raise AssertionError('cross-origin cancel accepted')
 except urllib.error.HTTPError as error:assert error.code==403
 assert not state.cancelled.is_set()
 assert broker_request(server.server_port,'/cancel','b'*24) is None and not state.cancelled.is_set()
 assert broker_request(server.server_port,'/cancel','a'*24)['cancelRequested'] and state.cancelled.is_set()
finally:server.shutdown();server.server_close();thread.join(timeout=3)
record={'status':'passed','crossProcessDuplicateBlocked':True,'actualWorkerCount':1,'loopbackStatusAndObservation':True,'crossOriginCancelDenied':True,'staleOtherTaskCancelDenied':True,'ownedCancelAccepted':True,'shopRegistration':'mock-only','realMerchantOAuth':'not-run','realMerchantWrites':'not-run'}
atomic_json(Path('.agent-work/auth-smoke/process-evidence.json'),record);print(json.dumps(record))
