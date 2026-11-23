"""Exercise MCP handshake, authenticated command delivery and redacted failure paths."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
EXPERT = ROOT/'workbuddy-expert'
ENTRY = EXPERT/'skills/heideng-merchant-beta/scripts/expert_mcp.py'
SPEC = importlib.util.spec_from_file_location('testable_expert_mcp', ENTRY)
MCP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MCP)


def message(method, rid=None, **params):
    body = {'jsonrpc':'2.0', 'method':method, 'params':params}
    if rid is not None:
        body['id'] = rid
    return body


class ExpertMcpTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root/'expert-distribution.json').write_text(json.dumps({'version':(ROOT/'VERSION').read_text().strip(),'inviteDigests':['fixture']}))
        self.key = 'synthetic-injected-key'
        self.beta = Mock(SKILL=root)
        self.beta.EligibilityError = type('EligibilityError',(ValueError,),{})
        self.service = MCP.MerchantService(self.beta, self.key)

    def connect(self, session):
        reply = session.respond(message('initialize',1,protocolVersion='2025-06-18'))
        self.assertEqual(reply['result']['protocolVersion'],'2025-06-18')
        self.assertIsNone(session.respond(message('notifications/initialized')))

    def test_manifest_matches_stdio_launcher_and_credential(self):
        config = json.loads((EXPERT/'.mcp.json').read_bytes())['mcpServers']['heideng-member']
        self.assertEqual(config['type'],'stdio')
        field = config['x-workbuddy']['auth']['tokenSchema']['fields'][0]
        self.assertEqual((field['key'],field['type'],field['required']),(MCP.KEY_ENV,'password',True))
        self.assertEqual(config['env'][field['key']],'${'+field['key']+'}')
        script = config['args'][-1].replace('${CODEBUDDY_PLUGIN_ROOT}',str(EXPERT))
        self.assertEqual(Path(script).resolve(), ENTRY)

    def test_disconnected_unresolved_and_rejected_keys_get_no_tools(self):
        for key in ('', '${HEIDENG_WORKBUDDY_INVITE_KEY}', 'fixture-rejected'):
            with self.subTest(key=key):
                self.beta.qualify.side_effect=ValueError('private detail '+key)
                session = MCP.Session(MCP.MerchantService(self.beta,key))
                self.assertIn('error',session.respond(message('tools/list',0)))
                reply = session.respond(message('initialize',1,protocolVersion='2025-11-25'))
                self.assertEqual(reply['error']['code'],-32001)
                self.assertNotIn('private detail',json.dumps(reply))
                self.assertIsNone(session.respond(message('notifications/initialized')))
                self.assertIn('error',session.respond(message('tools/list',2)))
        self.assertEqual(self.beta.qualify.call_count,1)
        self.beta.invoke.assert_not_called()

    def test_accepted_session_exposes_receipt_and_closes_cleanly(self):
        self.connect(MCP.Session(self.service))
        args = ['sample-context','--shop-id','51','--vender-id','42']
        def invoke(argv, *, key, run):
            self.assertEqual((argv,key),(args,self.key))
            return run([sys.executable,'-I','-B','merchant.py',*argv],env={}).returncode
        self.beta.invoke.side_effect = invoke
        child = subprocess.CompletedProcess([],0, stdout='progress\n'+json.dumps(
            {'selection':'matched','delivery':{'skuId':'101','status':'accepted'},'note':self.key},indent=2),
            stderr='private stderr '+self.key)
        stream = io.StringIO('\n'.join(json.dumps(payload) for payload in [
            message('initialize',1,protocolVersion='2025-06-18'), message('notifications/initialized'),
            message('ping',2), message('tools/list',3), message('tools/call',4,name='merchant_command',arguments={'arguments':args})])+'\n')
        output = io.StringIO()
        with patch.object(MCP.subprocess,'run',return_value=child) as run:
            MCP.serve(stream, output, self.service)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r['id'] for r in replies],[1,2,3,4])
        self.assertNotIn(self.key,output.getvalue())
        self.assertNotIn('stderr',output.getvalue())
        self.assertEqual(run.call_args.kwargs['stdin'],subprocess.DEVNULL)
        self.assertEqual(replies[2]['result']['tools'][0]['name'],'merchant_command')
        self.assertEqual(json.loads(replies[3]['result']['content'][0]['text'])['delivery']['status'],'accepted')
        self.assertFalse(replies[3]['result']['isError'])

    def test_secret_and_extra_inputs_rejected_and_failures_redacted(self):
        session = MCP.Session(self.service)
        self.connect(session)
        reply = session.respond(message('tools/call',2,name='merchant_command',arguments={
             'arguments':['status'],'key':self.key}))
        self.assertEqual(reply['error']['code'],-32602)
        reply = session.respond(message('tools/call',3,name='merchant_command',arguments={'arguments':['status',self.key]}))
        self.assertTrue(reply['result']['isError'])
        self.beta.invoke.assert_not_called()
        self.beta.invoke.side_effect = OSError('private detail '+self.key)
        reply = session.respond(message('tools/call',4,name='merchant_command',arguments={'arguments':['status']}))
        self.assertTrue(reply['result']['isError'])
        self.assertNotIn(self.key,json.dumps(reply))
        self.assertNotIn('private detail',json.dumps(reply))
        self.beta.invoke.side_effect = self.beta.EligibilityError('京麦连接器待核验')
        reply = session.respond(message('tools/call',5,name='merchant_command',arguments={'arguments':['run','connection']}))
        self.assertEqual(json.loads(reply['result']['content'][0]['text'])['message'],'京麦连接器待核验')
