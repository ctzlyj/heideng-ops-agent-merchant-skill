import contextlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import install
from heideng_merchant import SKILL_NAME
from heideng_merchant.distribution import verify_install
from heideng_merchant.official import OfficialClient
from heideng_merchant.safety import SafetyError
from heideng_merchant.auth_manager import AuthManager
from tests import test_auth_manager as fixture

class InstallHostFeedbackTests(unittest.TestCase):
 def test_joycode_defaults_to_observed_host_directory(self):
  with tempfile.TemporaryDirectory() as d:
   self.assertEqual(install.target_directory('joycode',home=d),Path(d)/'.joycode'/'skills'/SKILL_NAME)
   self.assertEqual(install.target_directory('universal',home=d),Path(d)/'.agents'/'skills'/SKILL_NAME)
 def test_explicit_host_directory_is_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   custom=Path(d)/'custom-skills'
   self.assertEqual(install.target_directory('joycode',home=d,skills_dir=str(custom)),custom/SKILL_NAME)
 def install_with_failure(self,error):
  with tempfile.TemporaryDirectory() as d,patch('install.OfficialClient') as client:
   client.return_value.ready.return_value=False
   client.return_value.install.side_effect=error
   client.return_value.shop_capability.return_value={'authAvailable':False,'platform':'unsupported','reason':'official-platform-not-supported'}
   output=io.StringIO()
   with contextlib.redirect_stdout(output):exitcode=install.main(['--home',d,'--host','joycode','--with-official'])
   result=json.loads(output.getvalue())
   self.assertEqual(exitcode,0);self.assertEqual(result['status'],'installed')
   self.assertTrue(verify_install(Path(d)/'.joycode'/'skills'/SKILL_NAME)['valid'])
   self.assertFalse(result['officialCli']['ready']);self.assertEqual(result['officialCli']['status'],'unavailable')
   self.assertIn('warnings',result);self.assertNotIn('internalVersionUntouched',result)
   self.assertNotIn('synthetic-private',json.dumps(result))
 def test_optional_cli_platform_failure_preserves_successful_skill_install(self):
  self.install_with_failure(SafetyError('official-platform-not-supported'))
 def test_optional_cli_network_failure_preserves_success_without_raw_error(self):
  self.install_with_failure(OSError('synthetic-private-network-body'))
 def test_optional_cli_error_does_not_publish_arbitrary_safety_message(self):
  self.install_with_failure(SafetyError('official-synthetic-private-response'))
 def test_failed_cli_refresh_does_not_hide_previously_verified_cli(self):
  with tempfile.TemporaryDirectory() as d,patch('install.OfficialClient') as client:
   client.return_value.ready.return_value=True
   client.return_value.install.side_effect=SafetyError('official-network-unavailable')
   client.return_value.shop_capability.return_value={'authAvailable':True,'platform':'windows-x64'}
   output=io.StringIO()
   with contextlib.redirect_stdout(output):exitcode=install.main(['--home',d,'--with-official'])
   result=json.loads(output.getvalue());self.assertEqual(exitcode,0)
   self.assertEqual(result['status'],'installed');self.assertTrue(result['officialCli']['ready'])
   self.assertIn('仍可用',result['warnings'][0]['text'])
 def test_package_validation_failure_is_still_blocked(self):
  with tempfile.TemporaryDirectory() as d:
   output=io.StringIO()
   with contextlib.redirect_stdout(output):exitcode=install.main(['--home',d,'--archive',str(Path(d)/'missing.zip'),'--sha256','0'*64])
   self.assertEqual(exitcode,2);self.assertEqual(json.loads(output.getvalue())['status'],'blocked')
 def test_official_capability_differentiates_download_and_auth_support(self):
  with tempfile.TemporaryDirectory() as d:
   windows=OfficialClient(Path(d),platform_name='windows-x64').shop_capability()
   arm=OfficialClient(Path(d),platform_name='macos-arm64').shop_capability()
   unsupported=OfficialClient(Path(d),platform_name='unsupported').shop_capability()
   self.assertTrue(windows['authAvailable']);self.assertTrue(arm['downloadSupported']);self.assertFalse(arm['authAvailable'])
   self.assertFalse(unsupported['downloadSupported']);self.assertFalse(unsupported['authAvailable'])
 def test_unsupported_auth_fails_before_runtime_or_receipt_creation(self):
  with tempfile.TemporaryDirectory() as d:
   runtime=fixture.Runtime();client=OfficialClient(Path(d),platform_name='unsupported')
   m=AuthManager(Path(d),client=client,runtime=runtime,starter=lambda *a,**kw:self.fail('worker started'))
   with self.assertRaisesRegex(SafetyError,'official-platform-not-supported'):m.start('synthetic-shop',foreground=True)
   self.assertEqual(runtime.calls,0);self.assertFalse((Path(d)/'tasks').exists())
 def test_macos_auth_safety_gate_also_preflights_before_runtime(self):
  with tempfile.TemporaryDirectory() as d:
   runtime=fixture.Runtime();client=OfficialClient(Path(d),platform_name='macos-arm64')
   m=AuthManager(Path(d),client=client,runtime=runtime)
   with self.assertRaisesRegex(SafetyError,'official-auth-secret-argv-backend-not-admitted'):m.start('synthetic-shop',foreground=True)
   self.assertEqual(runtime.calls,0)
 def test_onboarding_does_not_tell_unsupported_host_to_start_scan(self):
  from heideng_merchant import cli
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.cli.OfficialClient',return_value=OfficialClient(Path(d),platform_name='unsupported')):
   result=cli.run(cli.parser().parse_args(['--home',d,'onboarding']))
   self.assertFalse(result['shopCapability']['authAvailable'])
   self.assertTrue(any('平台' in x['text'] for x in result['steps']))
   self.assertFalse(any('扫码' in x['text'] for x in result['steps']))

 def test_install_output_preserves_known_capability_boolean(self):
  for platform,expected in (('unsupported',False),('macos-arm64',False),('windows-x64',True)):
   with self.subTest(platform=platform),tempfile.TemporaryDirectory() as d:
    client=OfficialClient(Path(d)/'synthetic-state',platform_name=platform)
    with patch('install.OfficialClient',return_value=client),patch.object(client,'install',side_effect=AssertionError('offline installer must not download CLI')):
     output=io.StringIO()
     with contextlib.redirect_stdout(output):exitcode=install.main(['--home',d,'--host','joycode','--offline'])
    result=json.loads(output.getvalue());self.assertEqual(exitcode,0)
    self.assertIs(result['shopCapability']['credentialExecutionAvailable'],expected)
    self.assertEqual(result['status'],'installed')
 def test_optional_cli_failure_keeps_capability_false_visible(self):
  with tempfile.TemporaryDirectory() as d:
   client=OfficialClient(Path(d)/'synthetic-state',platform_name='unsupported')
   with patch('install.OfficialClient',return_value=client),patch.object(client,'install',side_effect=SafetyError('official-platform-not-supported')):
    output=io.StringIO()
    with contextlib.redirect_stdout(output):exitcode=install.main(['--home',d,'--host','joycode','--with-official'])
   result=json.loads(output.getvalue());self.assertEqual(exitcode,0)
   self.assertIs(result['shopCapability']['credentialExecutionAvailable'],False)
   self.assertEqual(result['status'],'installed');self.assertIn('warnings',result)
 def test_install_boolean_exception_never_exposes_nonboolean_or_secret_fields(self):
  for value in ('synthetic-private-value',0,1,{'token':'synthetic-private-value'}):
   with self.subTest(value=value),tempfile.TemporaryDirectory() as d,patch('install.OfficialClient') as client:
    client.return_value.ready.return_value=False
    client.return_value.shop_capability.return_value={'credentialExecutionAvailable':value,'apiKey':False,'token':1}
    output=io.StringIO()
    with contextlib.redirect_stdout(output):exitcode=install.main(['--home',d,'--host','joycode','--offline'])
    result=json.loads(output.getvalue());self.assertEqual(exitcode,0)
    self.assertEqual(result['shopCapability']['credentialExecutionAvailable'],'[REDACTED]')
    self.assertEqual(result['shopCapability']['apiKey'],'[REDACTED]');self.assertEqual(result['shopCapability']['token'],'[REDACTED]')
    self.assertNotIn('synthetic-private',output.getvalue())
