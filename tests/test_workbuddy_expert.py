import hashlib
from functools import partial
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

from scripts.build_workbuddy_expert import ROOT, SKILL, build


def entry(path):
    spec = importlib.util.spec_from_file_location('workbuddy_beta_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def usage(balance=9, expires=0, unlimited=False):
    return {'code':True,'data':{'object':'token_usage','total_available':balance,
                                 'unlimited_quota':unlimited,'expires_at':expires}}


def active(_key):
    return {'object':'list','data':[{'id':'gpt-image-2.5','object':'model'},
                                    {'id':'gpt-image-2.6','object':'model'}]}


class WorkBuddyExpertTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.key = secrets.token_hex(32)
        self.digest = hashlib.sha256(self.key.encode()).hexdigest()
        self.beta = entry(ROOT/'workbuddy-expert'/SKILL/'scripts/beta.py')
        self.skill = self.root/'expert'
        self.skill.mkdir()
        (self.skill/'expert-distribution.json').write_text(json.dumps({
            'coreSha256':'c'*64,'inviteDigests':[self.digest]}))

    def test_an_ordinary_key_and_preview_cannot_enter_even_read_only_business(self):
        run, lookup = Mock(), Mock()
        with patch('heideng_merchant.merchant_key_store.read_key',return_value=secrets.token_hex(32)):
            with self.assertRaisesRegex(ValueError, '未获'):
                self.beta.invoke(['sample-context'],key=secrets.token_hex(32),skill=self.skill,home=self.root,lookup=lookup,run=run)
        with self.assertRaisesRegex(ValueError, '预览'):
            self.beta.qualify(self.key,[],lookup=lookup)
        run.assert_not_called()
        lookup.assert_not_called()

    def test_expiry_revocation_unavailable_and_zero_quota(self):
        check = lambda data: self.beta.qualify(self.key,[self.digest],lookup=lambda _k:data,active=active,now=lambda:100)
        self.assertIsNone(check(usage()))
        self.assertEqual(check(usage(0)), 'quota-exhausted')
        self.assertEqual(check(usage(unlimited=True)), 'unbounded-key')
        for invalid in [usage(expires=50), {'success':False}, {}, {'code':True,'data':{'object':'token_usage'}}]:
            with self.subTest(data=invalid), self.assertRaises(ValueError):
                check(invalid)
        for balance in (9,0):
            with self.subTest(balance=balance), self.assertRaisesRegex(ValueError,'当前可用'):
                self.beta.qualify(self.key,[self.digest],lookup=lambda _:usage(balance),
                                  active=lambda _: {'error':{'type':'invalid_request_error','code':'invalid_token'}})

    def test_only_invite_key_is_passed_to_execution_after_online_check(self):
        validated = []
        commands = []
        old = secrets.token_hex(32)
        def run(cmd, *, env):
            commands.append(cmd)
            self.assertNotIn(self.key,' '.join(cmd))
            if 'photo-listing' in cmd:
                self.assertEqual(env['HEIDENG_MERCHANT_LTS4AI_API_KEY'], self.key)
            else:
                self.assertNotIn('HEIDENG_MERCHANT_LTS4AI_API_KEY', env)
            self.assertNotIn('HEIDENG_MERCHANT_BETA_IMAGE_BLOCKED', env)
            self.assertEqual(env['HEIDENG_MERCHANT_HOME'], str(self.root/'.heideng-wb-beta'))
            return subprocess.CompletedProcess(cmd,0)
        def lookup(key):
            validated.append(hashlib.sha256(key.encode()).hexdigest())
            return usage(balance=9)
        with patch.dict(os.environ, {'HEIDENG_MERCHANT_LTS4AI_API_KEY':old}), \
                patch('heideng_merchant.merchant_key_store.read_key',return_value=self.key), \
                patch('heideng_merchant.distribution.verify_install',
                      return_value={'valid':True,'receipt':{'archiveSha256':'c'*64}}):
            self.assertEqual(self.beta.invoke(['sample-context'],skill=self.skill,home=self.root,key=self.key,lookup=lookup,active=active,run=run), 0)
            self.assertEqual(self.beta.invoke(['run','photo-listing','--','generate'],skill=self.skill,home=self.root,
                                             key=self.key,lookup=lookup,active=active,run=run), 0)
        self.assertEqual(validated,[self.digest]*2)
        self.assertEqual(len(commands),2)
        with self.assertRaisesRegex(ValueError,'凭证依赖未连接'):
            self.beta.invoke(['sample-context'],skill=self.skill,home=self.root,lookup=lookup,run=run)
        for argv in (['run','connection','--','ensure-shop','--shop','fixture'],
                     ['run','--entry','scripts/linker.py','connection','--','connect'],
                     ['run','materials','--','audit-pop-coverage']):
            with self.assertRaisesRegex(ValueError,'京麦连接器尚未接入'):
                self.beta.invoke(argv,key=self.key,skill=self.skill,home=self.root,lookup=lookup,active=active,run=run)
        self.assertEqual(len(commands),2)

    def test_expert_bundle_bootstraps_exact_core_in_a_new_workbuddy_home(self):
        invites = self.root/'digests.json'
        invites.write_text(json.dumps([self.digest]))
        with self.assertRaisesRegex(ValueError, '已上架京麦连接器'):
            build(self.root/'expert.zip', invites, 'operator@example.com')
        result = build(self.root/'expert.zip', invites, 'operator@example.com',integration_only=True)
        self.assertFalse(result['readyForSubmission'])
        self.assertEqual(result['invitedKeys'],1)
        with zipfile.ZipFile(result['file']) as z:
            config = json.loads(z.read('.codebuddy-plugin/plugin.json'))
            self.assertEqual(config['version'],(ROOT/'VERSION').read_text().strip())
            self.assertEqual(config['skills'], ['./'+SKILL])
            self.assertEqual(len(config['agents']),1)
            self.assertEqual([n for n in z.namelist() if n.endswith('/SKILL.md')], [SKILL+'/SKILL.md'])
            self.assertLess(len(z.read(config['avatar'])),500_000)
            self.assertEqual(z.read(SKILL+'/scripts/card.py'), (ROOT/'workbuddy-jd-connector/card.py').read_bytes())
            self.assertFalse(any(self.key.encode() in z.read(name) for name in z.namelist()))
            z.extractall(self.root/'workbuddy')
        skill = self.root/'workbuddy'/SKILL
        runtime = entry(skill/'scripts/beta.py')
        config = json.loads((skill/'expert-distribution.json').read_bytes())
        self.assertEqual(config['inviteDigests'],[self.digest])
        installs = []
        def offline(cmd, *, env):
            # Exercise the real installer and CLI while simulating external dependency services.
            if Path(cmd[3]).name == 'install.py':
                self.assertNotIn('HEIDENG_MERCHANT_LTS4AI_API_KEY',env)
                cmd = cmd + ['--offline']
                installs.append(cmd)
            proc = subprocess.run(cmd,env=env,capture_output=True,text=True,encoding='utf-8',timeout=90)
            self.assertEqual(proc.returncode,0,proc.stdout[-1000:])
            return proc
        with patch('heideng_merchant.merchant_key_store.read_key',return_value=self.key):
            for _ in range(2):
                self.assertEqual(runtime.invoke(['sample-context'],key=self.key,home=self.root,skill=skill,
                    lookup=lambda _:usage(),active=active,run=offline),0)
        self.assertEqual(len(installs),1)
        # Use the packaged MCP dispatcher and the installed core in a real child
        # process. A pending grant must reach the host intact with no remote read.
        mcp = entry(skill/'scripts/expert_mcp.py')
        service = mcp.MerchantService(runtime, self.key)
        receipt = self.root/'.heideng-wb-jd-card/jd-card/current.json'
        receipt.parent.mkdir(parents=True)
        attempt = 'a'*24
        receipt.write_text(json.dumps({'attempt':attempt,'profile':'wb-jd-'+attempt,'status':'pending'}))
        local_invoke = partial(runtime.invoke, skill=skill, home=self.root,
                               lookup=lambda _:usage(), active=active)
        with patch.object(runtime, 'invoke', local_invoke):
            result, failed = service.call(['card-shop-identity'])
        self.assertTrue(failed)
        self.assertEqual(result, {'status':'pending','matched':False})
        from heideng_merchant.distribution import install_archive, verify_install
        from heideng_merchant.safety import file_sha
        legacy = next((ROOT/'updates/artifacts').glob('*-0.4.10-*.zip'))
        old_home = self.root/'old'
        old_state = old_home/'.heideng-wb-beta'
        program = old_state/'program/heideng-ops-agent-merchant'
        install_archive(legacy,program,old_state,expected_sha=file_sha(legacy))
        note = old_state/'work/listing/fixture/receipt.json'
        note.parent.mkdir(parents=True)
        note.write_text('{"status":"UNKNOWN"}')
        with patch('heideng_merchant.merchant_key_store.read_key',return_value=self.key):
            self.assertEqual(runtime.invoke(['sample-context'],key=self.key,home=old_home,skill=skill,
                lookup=lambda _:usage(),active=active,run=offline),0)
        self.assertEqual(verify_install(program)['version'],config['version'])
        self.assertEqual(json.loads(note.read_bytes()),{'status':'UNKNOWN'})
        # Confirm the script can also bootstrap the nested zip in an actual isolated
        # interpreter. An empty roster stops the preview before key input or network.
        (skill/'expert-distribution.json').write_text(json.dumps(dict(config,inviteDigests=[])))
        proc = subprocess.run([sys.executable,'-I','-B',str(skill/'scripts/beta.py'),'sample-context'],
                              capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(proc.returncode,2,proc.stderr)
        self.assertFalse(json.loads(proc.stdout)['businessExecuted'])

    def test_expert_identity_only_uses_the_connected_cards_namespace(self):
        def probe(cmd, *, env):
            self.assertEqual(Path(cmd[3]), self.skill/'scripts/card.py')
            self.assertEqual(cmd[4:], ['--core',str(self.root/'.heideng-wb-beta/program/heideng-ops-agent-merchant'),
                                       '--state',str(self.root/'.heideng-wb-jd-card'),'identity'])
            self.assertNotIn('HEIDENG_MERCHANT_LTS4AI_API_KEY',env)
            return subprocess.CompletedProcess(cmd,0)
        call = lambda: self.beta.invoke(['card-shop-identity'],skill=self.skill,home=self.root,key=self.key,
                         lookup=lambda _:usage(),active=active,run=probe)
        self.assertEqual(call(), {'status':'not-connected','matched':False,'readOnly':True})
        marker = self.root/'.heideng-wb-jd-card/jd-card/current.json'
        marker.parent.mkdir(parents=True)
        marker.write_text('{}',encoding='utf-8')  # the adapter still has to verify this independently
        with patch('heideng_merchant.distribution.verify_install',
                   return_value={'valid':True,'receipt':{'archiveSha256':'c'*64}}):
            self.assertEqual(call(),0)
