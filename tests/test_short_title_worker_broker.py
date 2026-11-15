"""Bounded loopback queue protection; no merchant/browser/network calls."""
import importlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.safety import SafetyError
from tests import test_short_title_worker_state as original

class WorkerBrokerTests(unittest.TestCase):
 def module(self):
  self.assertIsNotNone(importlib.util.find_spec('heideng_merchant.short_title_worker_broker'),'worker broker missing')
  return importlib.import_module('heideng_merchant.short_title_worker_broker')
 def setup(self,d):
  state,c,j,run,root,cmd=original.WorkerStateTests().setup(d);m=self.module();return state,j,run,cmd,m.CommandBroker(d,j,run)
 def test_exact_local_headers_and_only_bounded_routes(self):
  m=self.module();h={'host':'127.0.0.1:12345','x-heideng-local':'1','x-heideng-worker':'a'*24,'x-heideng-fingerprint':'b'*64}
  self.assertTrue(m.allowed_request('GET','/status',h,12345,'a'*24,'b'*64))
  self.assertTrue(m.allowed_request('POST','/commands',h,12345,'a'*24,'b'*64))
  for patch in ({'origin':'https://untrusted.invalid'},{'referer':'https://untrusted.invalid'},{'host':'untrusted.invalid:12345'},{'x-heideng-worker':'c'*24},{'x-heideng-local':'0'},{'sec-fetch-site':'cross-site'},{'host':['127.0.0.1:12345','other']}):
   with self.subTest(patch=patch):self.assertFalse(m.allowed_request('POST','/commands',{**h,**patch},12345,'a'*24,'b'*64))
  for method,path in [('OPTIONS','/commands'),('POST','/execute'),('GET','/status?token=synthetic'),('GET','/status#other')]:self.assertFalse(m.allowed_request(method,path,h,12345,'a'*24,'b'*64))
 def test_parser_rejects_partial_duplicate_nonfinite_or_oversized_input(self):
  m=self.module()
  for raw,length in [(b'{}',3),(b'{"requestId":"a","requestId":"b"}',len(b'{"requestId":"a","requestId":"b"}')),(b'{"ttl":NaN}',11),(b'x'*4097,4097),(b'[]',2),(b'\xff',1)]:
   with self.subTest(raw=raw[:40]),self.assertRaises(SafetyError):m.parse_command(raw,length)
 def test_same_request_id_is_queued_once_and_changed_body_never_runs(self):
  with tempfile.TemporaryDirectory() as d:
   state,j,run,cmd,b=self.setup(d);first=b.submit(cmd);again=b.submit(cmd);self.assertEqual(first['requestId'],again['requestId'])
   self.assertEqual(b.pending_count(),1)
   with self.assertRaises(SafetyError):b.submit({**cmd,'action':'effects'})
   self.assertEqual(b.pending_count(),1)
 def test_completed_or_unknown_original_never_reenters_the_queue(self):
  with tempfile.TemporaryDirectory() as d:
   state,j,run,cmd,b=self.setup(d);b.submit(cmd);accepted=b.take();dispatch=state.dispatch_command(d,j,run,accepted)
   self.assertEqual(b.submit(cmd)['status'],'original-command-outcome-unknown');self.assertEqual(b.pending_count(),0)
   state.write_result(d,j,run,accepted,dispatch,{'status':'submitted','imported':False});self.assertEqual(b.submit(cmd)['status'],'completed');self.assertEqual(b.pending_count(),0)
 def test_stop_is_queued_not_native_action_and_preserves_no_write_approval(self):
  with tempfile.TemporaryDirectory() as d:
   state,j,run,cmd,b=self.setup(d);b.submit({**cmd,'action':'stop'});self.assertTrue(b.stop_requested.is_set())
   self.assertEqual(b.pending_count(),1);accepted=b.take();self.assertEqual(accepted['command']['action'],'stop');self.assertFalse(accepted['command']['confirmed']);self.assertFalse(state.file(d,'short-title-worker-dispatches',j['workerId'],cmd['requestId']).exists())
 def test_private_or_wrong_root_never_stops_or_queues(self):
  with tempfile.TemporaryDirectory() as d:
   state,j,run,cmd,b=self.setup(d)
   for extra in ({'token':'SYNTHETIC_ONLY'},{'fingerprint':'0'*64},{'action':'shell'},{'confirmed':True}):
    with self.subTest(extra=extra),self.assertRaises(SafetyError):b.submit({**cmd,**extra})
   self.assertEqual(b.pending_count(),0);self.assertFalse(b.stop_requested.is_set())
 def test_lost_accepted_original_is_not_recreated_from_memory(self):
  with tempfile.TemporaryDirectory() as d:
   state,j,run,cmd,b=self.setup(d);b.submit(cmd);state.file(d,'short-title-worker-commands',j['workerId'],cmd['requestId']).unlink()
   with self.assertRaises(SafetyError):b.submit(cmd)
 def test_queue_full_refuses_before_accepting_new_command(self):
  with tempfile.TemporaryDirectory() as d:
   state,j,run,cmd,b=self.setup(d);b.max_pending=1;b.submit(cmd)
   other={**cmd,'requestId':'d'*32}
   with self.assertRaises(SafetyError):b.submit(other)
   self.assertEqual(state.command_status(d,j,other['requestId'])['status'],'not-found')

if __name__=='__main__':unittest.main(verbosity=2)
