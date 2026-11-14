"""Result-binding controller tests use a synthetic writer, not an API specification."""
import copy,tempfile,unittest
from pathlib import Path
from heideng_merchant.operations import Operations
from heideng_merchant.safety import SafetyError

class Client:
 def __init__(self):self.calls=[];self.unknown=False;self.foreign=False;self.ack={'imgId':'asset-9'};self.detail={'imgId':'asset-9','imgName':'sample.png','categoryId':7}
 def identity(self,p):return {'venderId':'2' if self.foreign else '1','shopId':'3','shopName':'synthetic-store','shopType':'POP'}
 def invoke(self,p,url,**kw):
  self.calls.append((url,kw))
  if kw.get('method','GET')!='GET':
   if self.unknown:raise TimeoutError('synthetic unknown')
   return {'data':copy.deepcopy(self.ack)}
  return {'data':copy.deepcopy(self.detail)}

class ResultBindingTests(unittest.TestCase):
 def make(self,d):
  c=Client();ops=Operations(Path(d),c);ops.connect('merchant-test','synthetic-store','1');op={'url':'/rest/sp-product/v0/synthetic-assets','method':'POST','params':{},'body':{'syntheticOnly':True}}
  verify={'query':{'url':'/rest/sp-product/v0/media-zones/{zoneId}/images/{imageId}','params':{'zoneId':'img_test','imageId':{'$result':'imgId'}},'skillId':'jdo-product-material'},'expected':{'imgId':{'$result':'imgId'},'categoryId':7,'imgName':'sample.png'}}
  return c,ops,op,verify
 def submit(self,ops,task):ops.approve(task['taskId'],task['fingerprint'],confirmed=True);return ops.execute(task['taskId'])
 def test_bound_receipt_id_resolves_only_original_query_and_fixed_evidence(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,op,verify=self.make(d);task=ops.prepare('merchant-test',op,result_verification=verify);self.submit(ops,task);read=ops.verify_result(task['taskId']);self.assertEqual(read['status'],'verified');self.assertEqual(c.calls[-1][1]['params']['imageId'],'asset-9');self.assertEqual(read['resultReadback']['sourceResultSha256'],read['resultReceiptSha256'])
 def test_unknown_or_missing_original_receipt_cannot_be_replaced_by_target_match(self):
  for kind in ('unknown','missing'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
    c,ops,op,verify=self.make(d);task=ops.prepare('merchant-test',op,result_verification=verify);c.unknown=kind=='unknown';c.ack={} if kind=='missing' else c.ack;self.submit(ops,task);count=len(c.calls)
    with self.assertRaises(SafetyError):ops.verify_result(task['taskId'])
    self.assertEqual(len(c.calls),count)
    with self.assertRaises(SafetyError):ops.prepare('merchant-test',{**op,'body':{'syntheticOnly':False}},result_verification=verify)
 def test_changed_result_binding_changes_fingerprint(self):
  with tempfile.TemporaryDirectory() as d:
   c,ops,op,verify=self.make(d);a=ops.prepare('merchant-test',op,result_verification=verify);verify['expected']['categoryId']=8;b=ops.prepare('merchant-test',op,result_verification=verify);self.assertNotEqual(a['fingerprint'],b['fingerprint'])
 def test_unsafe_reference_fields_or_nonpath_dynamic_params_rejected_before_write(self):
  for kind in ('secret','path','extra','nonpath'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
    c,ops,op,verify=self.make(d)
    if kind=='secret':verify['query']['params']['imageId']={'$result':'access_token'}
    elif kind=='path':verify['query']['params']['imageId']={'$result':'data.imgId'}
    elif kind=='extra':verify['query']['params']['imageId']={'$result':'imgId','extra':1}
    else:verify['query']['params']['unrelated']={'$result':'imgId'}
    with self.assertRaises(SafetyError):ops.prepare('merchant-test',op,result_verification=verify)
    self.assertEqual(c.calls,[])
 def test_invalid_or_swapped_receipt_and_wrong_shop_never_verify(self):
  for kind in ('path-id','foreign','field-mismatch','modified-result'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
    c,ops,op,verify=self.make(d);task=ops.prepare('merchant-test',op,result_verification=verify)
    if kind=='path-id':c.ack['imgId']='../../foreign'
    self.submit(ops,task)
    if kind=='foreign':c.foreign=True
    elif kind=='field-mismatch':c.detail['categoryId']=8
    elif kind=='modified-result':
     from heideng_merchant.safety import atomic_json
     state=ops.task(task['taskId']);state['result']['data']['imgId']='other';atomic_json(ops._path(task['taskId']),state)
    if kind=='field-mismatch':self.assertNotEqual(ops.verify_result(task['taskId'])['status'],'verified')
    else:
     with self.assertRaises(SafetyError):ops.verify_result(task['taskId'])

if __name__=='__main__':unittest.main()
