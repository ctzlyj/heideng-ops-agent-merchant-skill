import json,tempfile,unittest
from pathlib import Path
from heideng_merchant.updates import ReleaseUpdates
from heideng_merchant.safety import SafetyError

class UpdateTests(unittest.TestCase):
 def test_release_discovery_is_read_only_and_exact_repository(self):
  calls=[]
  class Result:
   returncode=0;stderr='';stdout=json.dumps({'tag_name':'v0.1.0','draft':False,'prerelease':False,'assets':[{'name':'heideng-ops-agent-merchant-0.1.0.zip','size':100},{'name':'SHA256SUMS','size':100}]})
  def runner(args,**kwargs):calls.append((args,kwargs));return Result()
  with tempfile.TemporaryDirectory() as d:
   u=ReleaseUpdates(Path(d),runner=runner);r=u.check('0.0.1');self.assertTrue(r['updateAvailable']);self.assertIn('ctzlyj/heideng-ops-agent-merchant-skill',calls[0][0][2]);self.assertNotIn('JD_LLM_API_KEY',calls[0][1]['env'])
 def test_lower_release_never_downgrades(self):
  class Result:
   returncode=0;stdout='{"tag_name":"v0.1.0","assets":[],"draft":false,"prerelease":false}';stderr=''
  with tempfile.TemporaryDirectory() as d:
   r=ReleaseUpdates(Path(d),runner=lambda *a,**k:Result()).check('0.2.0');self.assertFalse(r['updateAvailable']);self.assertEqual(r['status'],'current-or-newer')
 def test_invalid_tag_rejected(self):
  class Result:
   returncode=0;stdout='{"tag_name":"../bad"}';stderr=''
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(SafetyError):ReleaseUpdates(Path(d),runner=lambda *a,**k:Result()).check('0.1.0')
 def test_missing_release_does_not_claim_installed(self):
  class Result:
   returncode=1;stdout='';stderr='synthetic denied'
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(SafetyError):ReleaseUpdates(Path(d),runner=lambda *a,**k:Result()).check('0.1.0')

if __name__=='__main__':unittest.main()
