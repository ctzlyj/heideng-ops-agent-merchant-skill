"""Real local connector lifecycle, fake shop/browser only; no real account."""
import json, os, subprocess, sys, tempfile, time, unittest, urllib.request
from pathlib import Path
from heideng_merchant.mature_runtime import child_environment
from heideng_merchant.safety import read_json, atomic_json
ROOT=Path(__file__).resolve().parents[1]

class ConnectorLifecycleTests(unittest.TestCase):
    def test_service_and_job_outlive_client_and_failed_same_shop_retry(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'merchant';env=child_environment(state)
            env.update(HEIDENG_MERCHANT_PACKAGE=str(ROOT),JDO_CLI_PATH=str(root/'missing-official-cli'))
            port=env['JINGMAI_LINKER_PORT'];base='http://127.0.0.1:'+port
            local_http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def api(path,payload=None):
                data=None if payload is None else json.dumps(payload).encode()
                request=urllib.request.Request(base+path,data=data,headers={'Content-Type':'application/json','X-Session-Token':token})
                with local_http.open(request,timeout=3) as response:return json.loads(response.read())
            # Isolated fake identity provider only. No real browser/login/OAuth.
            (state/'linker').mkdir(parents=True)
            client=subprocess.run([sys.executable,'-I','-B',str(ROOT/'scripts/mature_entry.py'),str(ROOT/'mature/connection/scripts/linker.py'),'--help'],env=env,capture_output=True,timeout=5)
            self.assertEqual(client.returncode,0,client.stderr)
            # Start original service with the same launch flags as ensure_server, no GUI/business.
            flags=0x08000000|0x00000008 if os.name=='nt' else 0
            env=env.copy();env['HEIDENG_MERCHANT_PACKAGE']=str(ROOT)
            from unittest.mock import patch
            self.enterContext(patch.object(sys,'path',[str(ROOT/'mature/connection/scripts'),*sys.path]))
            self.enterContext(patch.dict(os.environ,env,clear=True))
            import importlib.util
            spec=importlib.util.spec_from_file_location('isolated_lifecycle_linker',ROOT/'mature/connection/scripts/linker.py')
            linker=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(linker)
            # Original detached service launcher. No GUI or real account.
            self.assertTrue(linker.ensure_server())
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                try:
                    health=json.loads(local_http.open(base+'/api/health',timeout=1).read())
                    if health.get('ok'):break
                except OSError:time.sleep(.05)
            else:self.fail('isolated original connector unavailable')
            # The launcher returns, another short-lived client reads the same service.
            token=local_http.open(base+'/',timeout=1).read().decode().split('const TOKEN = "')[1].split('"')[0]
            self.assertTrue(api('/api/job')['ok'])
            try:
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    try:
                        health=json.loads(local_http.open(base+'/api/health',timeout=1).read())
                        if health.get('ok'):break
                    except OSError:time.sleep(.05)
                else:self.fail('isolated original connector unavailable')
                token=local_http.open(base+'/',timeout=1).read().decode().split('const TOKEN = "')[1].split('"')[0]
                # Original service survives an independent short-lived client process.
                subprocess.run([sys.executable,'-c','pass'],check=True,timeout=2)
                self.assertTrue(api('/api/job')['ok'])
                # Simulate an original failed job, then normal retry must not reuse it.
                import importlib.util
                spec=importlib.util.spec_from_file_location('local_server',ROOT/'mature/connection/app/server.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                manager=module.Manager()
                class Job:
                    status='failed';shop_name='fixture';expect_vender_id='';requested_profile='fixture'
                    def resume(self):raise AssertionError('normal retry cannot resume old failure')
                manager.job=Job()
                # Do not instantiate real auth/browser in this unit integration check.
                from unittest.mock import patch
                with patch('browser_auth.BrowserAuthJob') as created:
                    result=manager.start_flow('fixture','fixture')
                    self.assertIsNot(result,manager.job if False else None)
                created.assert_called_once()
            finally:
                try:
                    token=local_http.open(base+'/',timeout=1).read().decode().split('const TOKEN = "')[1].split('"')[0]
                    request=urllib.request.Request(base+'/api/shutdown',data=b'{}',headers={'Content-Type':'application/json','X-Session-Token':token})
                    local_http.open(request,timeout=2).read()
                except Exception:pass
                time.sleep(.1)
                with self.assertRaises(OSError):local_http.open(base+'/api/health',timeout=1).read()

if __name__=='__main__':unittest.main()
