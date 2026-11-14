import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.cli import parser,run
from heideng_merchant.safety import SafetyError

class AuthCliTests(unittest.TestCase):
 def test_agent_can_get_auth_status_observe_cancel_and_recover(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.cli.AuthManager') as manager:
   manager.return_value.status.return_value={'stage':'waiting_login','ready':False}
   manager.return_value.observe.return_value={'ready':False}
   manager.return_value.cancel.return_value={'cancelRequested':True}
   manager.return_value.recover.return_value={'oauthReplayed':False}
   for command,method in [('auth-status','status'),('auth-observe','observe'),('auth-cancel','cancel'),('auth-recover','recover')]:
    result=run(parser().parse_args(['--home',d,command,'--task-id','a'*24]));self.assertIsInstance(result,dict);getattr(manager.return_value,method).assert_called_once_with('a'*24)
 def test_foreground_flag_reaches_start_without_user_profile_or_code(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.cli.AuthManager') as manager:
   manager.return_value.start.return_value={'ready':False};manager.return_value.ensure_shop.return_value={'ready':True}
   run(parser().parse_args(['--home',d,'auth-start','--shop-name','test-shop','--foreground']))
   manager.return_value.start.assert_called_once_with('test-shop',vender_id=None,foreground=True)
   run(parser().parse_args(['--home',d,'ensure-shop','--shop-name','test-shop']))
   manager.return_value.ensure_shop.assert_called_once_with('test-shop',vender_id=None,foreground=False)

if __name__=='__main__':unittest.main()

class AuthRetryCliTests(unittest.TestCase):
 def test_safe_restart_passes_original_receipt_and_foreground_flag(self):
  with tempfile.TemporaryDirectory() as d,patch('heideng_merchant.cli.AuthManager') as manager:
   manager.return_value.restart.return_value={'ready':False}
   result=run(parser().parse_args(['--home',d,'auth-restart','--task-id','a'*24,'--foreground']))
   self.assertFalse(result['ready']);manager.return_value.restart.assert_called_once_with('a'*24,foreground=True)
