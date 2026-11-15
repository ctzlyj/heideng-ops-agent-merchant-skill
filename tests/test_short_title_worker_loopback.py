"""Actual loopback HTTP, synthetic browser and business client, owning main thread."""
import json,socket,tempfile,threading,time,unittest
from unittest.mock import patch
from heideng_merchant.safety import SafetyError
from heideng_merchant import short_title_worker_state as original
from heideng_merchant.short_title_worker_service import ShortTitleWorkerService,broker_request
from tests import test_short_title_worker as core_fixture

class WorkerLoopbackTests(unittest.TestCase):
 def test_actual_loopback_once_only_native_actions_on_browser_owner(self):
  with tempfile.TemporaryDirectory() as d:
   fixture=core_fixture.WorkerLifecycleTests();w,c,j,run,source,native=fixture.make(d);owner=threading.get_ident();native_threads=[];errors=[];reads=[]
   old=native.driver.context.new_page
   def page():
    p=old();emit=p.emit
    def record(response):native_threads.append(threading.get_ident());return emit(response)
    p.emit=record;return p
   native.driver.context.new_page=page
   service=ShortTitleWorkerService(d,client=c,runtime_verifier=lambda:j['scope']['runtime'],startup_wait=0)
   connect=socket.create_connection
   def local_only(address,*args,**kwargs):
    if address[0]!='127.0.0.1':raise AssertionError('external socket denied')
    return connect(address,*args,**kwargs)
   def completed(rid):
    until=time.monotonic()+15
    while time.monotonic()<until:
     try:
      out=service.command_status(j['workerId'],rid)
      if out['status']=='completed':return out
     except SafetyError:pass
     time.sleep(.01)
    raise AssertionError('original local command did not complete')
   def client():
    try:
     until=time.monotonic()+15
     while time.monotonic()<until:
      try:out=service.status(j['workerId'])
      except SafetyError:out={}
      if out.get('ready') and out.get('importId'):break
      time.sleep(.01)
     else:raise AssertionError('owning worker did not become ready')
     # Active start must read this live actor, not re-lock or spawn another.
     self.assertEqual(service.start(j['scope']['planId'],foreground=True)['runId'],run['runId'])
     root=original.read_link(d,j);kwargs={'import_id':root['importId'],'fingerprint':root['fingerprint']}
     service.command(j['workerId'],'approve',confirmed=True,request_id='a'*32,**kwargs);completed('a'*32)
     first=service.command(j['workerId'],'execute',**kwargs);result=completed(first['requestId']);reads.append(result)
     repeat=service.command(j['workerId'],'execute',**kwargs);self.assertEqual(first['requestId'],repeat['requestId']);self.assertEqual(repeat['status'],'completed')
     for action,rid in (('results','c'*32),('effects','d'*32)):
      service.command(j['workerId'],action,request_id=rid,**kwargs);reads.append(completed(rid))
     service.command(j['workerId'],'stop',request_id='f'*32)
    except BaseException as e:errors.append(e)
    finally:
     if w.broker is not None:w.broker.stop_requested.set()
   with patch('socket.create_connection',side_effect=local_only):
    thread=threading.Thread(target=client,daemon=True);thread.start()
    try:out=w.run()
    finally:thread.join(timeout=20)
   self.assertFalse(thread.is_alive());self.assertFalse(errors,[str(e) for e in errors]);self.assertEqual(out['status'],'closed')
   self.assertEqual((native.driver.context.page.uploads,native.driver.context.page.creates),(1,1));self.assertEqual(set(native_threads),{owner});self.assertFalse(c.posts)
   self.assertFalse(reads[0]['result']['imported']);self.assertTrue(all(r['historicalResult'] for r in reads));self.assertEqual(service.status(j['workerId'])['status'],'closed')
 def test_broker_freeze_rejects_new_http_command_and_bad_origin_never_queues(self):
  from heideng_merchant.short_title_worker_broker import CommandBroker,make_server
  from tests import test_short_title_worker_state as state_fixture
  import http.client
  with tempfile.TemporaryDirectory() as d:
   mod,c,j,r,root,cmd=state_fixture.WorkerStateTests().setup(d);broker=CommandBroker(d,j,r);server=make_server(broker);thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
   headers={'Host':'127.0.0.1:'+str(server.server_port),'X-Heideng-Local':'1','X-Heideng-Worker':j['workerId'],'X-Heideng-Fingerprint':j['fingerprint'],'Content-Type':'application/json'}
   try:
    for extra in ({'Origin':'https://synthetic.invalid'},{}):
     if not extra:broker.freeze()
     connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3);connection.request('POST','/commands',body=json.dumps(cmd),headers={**headers,**extra});response=connection.getresponse();self.assertIn(response.status,(400,403));response.read();connection.close()
    self.assertEqual(broker.pending_count(),0);self.assertEqual(mod.command_status(d,j,cmd['requestId'])['status'],'not-found')
   finally:server.shutdown();thread.join(timeout=3);server.server_close()
