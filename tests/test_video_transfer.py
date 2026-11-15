"""No live DNS/network: exact bytes and non-replay upload semantics."""
import hashlib,io,tempfile,time,unittest,uuid
from pathlib import Path
from heideng_merchant.safety import SafetyError
from heideng_merchant.video_transfer import UploadGrant,transfer_video

class VideoTransferTests(unittest.TestCase):
 def inputs(self,d):
  raw=b'synthetic video bytes'*20;path=Path(d)/'source.mp4';path.write_bytes(raw);sha=hashlib.sha256(raw).hexdigest();secret=uuid.uuid4().hex;return path,raw,sha,UploadGrant(900,'https://upload.example.test/video?grant='+secret),secret
 def backend(self,calls,*,mutate=None,status=200):
  class Response:
   def __init__(self):self.status=status;self.raw=io.BytesIO(b'acknowledgement')
   def read(self,n):return self.raw.read(n)
  class Connection:
   def __init__(self,*a,**k):calls.append(self);self.headers=[];self.data=[];self.request=None
   def putrequest(self,*a,**k):self.request=a
   def putheader(self,*a):self.headers.append(a)
   def endheaders(self):
    if mutate:mutate()
   def send(self,b):self.data.append(b)
   def getresponse(self):return Response()
   def close(self):self.closed=True
  return Connection
 def dns(self,*a,**k):return [(2,1,6,'',('8.8.8.8',443))]
 def test_multipart_uses_video_file_original_bytes_and_no_auth_headers(self):
  with tempfile.TemporaryDirectory() as d:
   path,raw,sha,grant,secret=self.inputs(d);calls=[];result=transfer_video(grant,path,sha,len(raw),time.time()+900,resolver=self.dns,connection_factory=self.backend(calls))
   self.assertEqual(len(calls),1);self.assertEqual(calls[0].request[0],'POST');data=b''.join(calls[0].data);self.assertIn(b'name="video_file"',data);self.assertIn(raw,data);self.assertEqual(result['sentBytes'],len(raw));self.assertFalse(result['storageVerified']);self.assertNotIn(secret,repr(result));self.assertFalse(any(k.lower() in ('cookie','authorization') for k,v in calls[0].headers));self.assertTrue(calls[0].closed)
 def test_replaced_source_rejected_before_any_connection(self):
  with tempfile.TemporaryDirectory() as d:
   path,raw,sha,grant,secret=self.inputs(d);path.write_bytes(b'X'*len(raw));calls=[]
   with self.assertRaises(SafetyError):transfer_video(grant,path,sha,len(raw),time.time()+900,resolver=self.dns,connection_factory=self.backend(calls))
   self.assertFalse(calls,'unapproved source contacted upload server')
 def test_source_mutation_during_connection_cannot_change_uploaded_bytes(self):
  with tempfile.TemporaryDirectory() as d:
   path,raw,sha,grant,secret=self.inputs(d);calls=[];mutate=lambda:path.write_bytes(b'X'*len(raw))
   result=transfer_video(grant,path,sha,len(raw),time.time()+900,resolver=self.dns,connection_factory=self.backend(calls,mutate=mutate))
   self.assertEqual(result['originalSha256'],sha);self.assertIn(raw,b''.join(calls[0].data))
 def test_private_or_mixed_dns_and_redirect_response_cannot_retry(self):
  for ips,status in ((['127.0.0.1'],200),(['8.8.8.8','10.0.0.1'],200),(['8.8.8.8'],302)):
   with tempfile.TemporaryDirectory() as d:
    path,raw,sha,grant,secret=self.inputs(d);calls=[];dns=lambda *a,**k:[(2,1,6,'',(ip,443)) for ip in ips]
    with self.assertRaises(SafetyError):transfer_video(grant,path,sha,len(raw),time.time()+900,resolver=dns,connection_factory=self.backend(calls,status=status))
    self.assertLessEqual(len(calls),1)
 def test_expired_approval_never_connects(self):
  with tempfile.TemporaryDirectory() as d:
   path,raw,sha,grant,secret=self.inputs(d);calls=[]
   with self.assertRaises(SafetyError):transfer_video(grant,path,sha,len(raw),0,resolver=self.dns,connection_factory=self.backend(calls))
   self.assertFalse(calls)

class VideoTransferDeadlineReviewTests(unittest.TestCase):
 inputs=VideoTransferTests.inputs
 dns=VideoTransferTests.dns
 def test_callback_crossing_deadline_does_not_launch_http_headers(self):
  with tempfile.TemporaryDirectory() as d:
   path,raw,sha,grant,secret=self.inputs(d);clock=[100];headers=[]
   class Connection:
    def __init__(self,*a,**kw):pass
    def putrequest(self,*a,**kw):pass
    def putheader(self,*a,**kw):pass
    def endheaders(self):headers.append(clock[0])
    def close(self):pass
   def before():clock[0]=102
   with self.assertRaises(SafetyError):transfer_video(grant,path,sha,len(raw),101,resolver=self.dns,connection_factory=Connection,clock=lambda:clock[0],before_dispatch=before)
   self.assertFalse(headers,'HTTP launched after approval expired while persisting marker')

class VideoUploadResponseSafetyTests(unittest.TestCase):
 inputs=VideoTransferTests.inputs
 dns=VideoTransferTests.dns
 def test_explicit_negative_json_with_http200_is_not_a_transfer_ack(self):
  with tempfile.TemporaryDirectory() as d:
   path,raw,sha,grant,secret=self.inputs(d)
   class Response:
    status=200
    def __init__(self):self.data=io.BytesIO(b'{"success":false,"data":{}}')
    def read(self,n):return self.data.read(n)
   class Connection:
    def __init__(self,*a,**kw):pass
    def putrequest(self,*a,**kw):pass
    def putheader(self,*a,**kw):pass
    def endheaders(self):pass
    def send(self,*a):pass
    def getresponse(self):return Response()
    def close(self):pass
   with self.assertRaises(SafetyError):transfer_video(grant,path,sha,len(raw),time.time()+900,resolver=self.dns,connection_factory=Connection)
 def test_multicast_is_not_an_allowed_public_https_upload_target(self):
  helper=VideoTransferTests()
  with tempfile.TemporaryDirectory() as d:
   path,raw,sha,grant,secret=self.inputs(d);calls=[];resolver=lambda *a,**kw:[(2,1,6,'',('224.0.0.1',443))]
   with self.assertRaises(SafetyError):transfer_video(grant,path,sha,len(raw),time.time()+900,resolver=resolver,connection_factory=helper.backend(calls))
   self.assertFalse(calls)
