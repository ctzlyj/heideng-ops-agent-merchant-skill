"""Offline regression: two real CLI processes, one accepted authorization, first response lost."""
import argparse
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace


def execute(package, prefix=None, merchant=False):
    with tempfile.TemporaryDirectory(prefix='pop-connect-contract-') as directory:
        state = Path(directory).resolve()
        env = {**os.environ, 'HEIDENG_MERCHANT_HOME':str(state), 'PYTHONUTF8':'1',
               'JDO_HOME':str(state/'cli-home/.jdo-cli'), 'JINGMAI_LINKER_HOME':str(state/'linker'),
               'USERPROFILE':str(state), 'HOME':str(state), 'NO_PROXY':'localhost,127.0.0.1'}
        if merchant:
            skills = state/'skills'
            args = [sys.executable, str(package/'install.py'), '--skills-dir',str(skills),
                    '--state',str(state), '--offline','--no-auto-update']
            subprocess.run(args, env=env, check=True, capture_output=True, timeout=180)
            package = skills/'heideng-ops-agent-merchant'
            prefix = [sys.executable, str(package/'scripts/merchant.py'), '--state',str(state), 'run','connection','--']
        connector = package/'mature/connection' if merchant else package
        if prefix is None:
            prefix = [sys.executable, str(connector/'scripts/linker.py')]
        fake = state/'tools/fixture/jdo-cli.exe'
        fake.parent.mkdir(parents=True)
        # Only discovery is required for a new profile. No official executable runs.
        fake.write_bytes(b'non-executable discovery fixture')
        fake.chmod(0o700)
        env['JDO_CLI_PATH'] = str(fake)
        (state/'tools/official.json').write_text(json.dumps({'root':'tools/fixture','executable':fake.name,
            'executableSha256':sha256(fake.read_bytes()).hexdigest()}))
        spec = importlib.util.spec_from_file_location('dispatch_contract', connector/'app/pop_connection.py')
        shared = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(shared)
        service = (connector/'app/server.py').read_text(encoding='utf-8')
        version = re.search(r'^SERVER_VERSION\s*=\s*"([^"]+)"',service,re.M).group(1)
        received = []
        job = SimpleNamespace(id='fixture-native-job', requested_profile='fixture-src',
                              profile='fixture-src-1234abcd', stage='waiting_login')
        job.to_dict = lambda: {'id':job.id, 'profile':job.profile, 'stage':job.stage, 'status':'waiting'}
        class LocalService(BaseHTTPRequestHandler):
            def reply(self, status, value):
                body = value.encode() if isinstance(value,str) else json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path == '/':
                    self.reply(200,'const TOKEN = "fixture-no-account";')
                elif self.path == '/api/health':
                    self.reply(200, {'ok':True, 'version':version})
                elif self.path == '/api/job':
                    self.reply(200, {'ok':True, 'job':job.to_dict()})
                else:
                    self.reply(404,{})

            def do_POST(self):
                if self.path != '/api/connect':
                    self.reply(404,{})
                    return
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append(payload['authorizationRequestId'])
                shared.admit(state/'linker', payload, lambda:job)
                self.reply(503, {'message':'synthetic lost acknowledgement'})

        port = 18000 + int(sha256(str(state).encode()).hexdigest()[:6],16) % 20000 if merchant else 0
        with ThreadingHTTPServer(('127.0.0.1',port), LocalService) as server:
            env['JINGMAI_LINKER_PORT'] = str(server.server_port)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                args = [*prefix,'ensure-shop','--shop','Fixture POP','--profile','fixture-src','--no-open','--no-wait']
                if not merchant:
                    args.append('--allow-auth')
                results = []
                for _ in range(2):
                    proc = subprocess.run(args, env=env, capture_output=True, text=True, encoding='utf-8',
                                          errors='replace', timeout=90)
                    try:
                        results.append(json.loads(proc.stdout))
                    except ValueError as exc:
                        raise AssertionError((proc.returncode,proc.stdout[-500:],proc.stderr[-500:])) from exc
            finally:
                server.shutdown()
                thread.join(5)
        first, second = results
        assert first.get('errorKind') == 'result_unknown' and first.get('ok') is False, first
        assert second.get('status') == 'awaiting_auth' and second.get('jobId') == job.id, second
        assert second.get('profile') == job.profile and len(received) == 1, (second,received)
        print(json.dumps({'accepted':1,'posts':len(received),'originalJobRestored':True,'authorizedStores':0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--merchant-root',type=Path)
    parser.add_argument('--entry-json')
    args = parser.parse_args()
    root = args.merchant_root or Path(__file__).resolve().parents[1]
    execute(root, prefix=json.loads(args.entry_json) if args.entry_json else None,
            merchant=(root/'scripts/merchant.py').is_file())
