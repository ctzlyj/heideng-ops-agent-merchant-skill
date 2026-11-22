"""Install the checked-out PR into an isolated WorkBuddy and resume a lost edit response.

Only the host dialogue and the external shop/media services are simulated. Connection,
eligibility, upload deduplication, task discovery and readback use the installed code.
"""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'hm-fixture'
IDENTITY = {'venderId': '99', 'shopBaseInfo': {'shopId': '77', 'shopName':'fixture', 'type':0, 'status':1}}


def execute_stage(target, home, stage):
    from PIL import Image
    sys.path[:0] = [str(target),str(target/'mature/connection/scripts'),str(target/'mature/listing/scripts'),
                    str(ROOT/'tests')]
    import linker
    import image_patch_update as images
    from heideng_merchant.safety import atomic_json
    from test_category_sku_edit import Platform

    def no_external(*args, **kwargs):
        raise AssertionError('The merchant journey attempted an external connection')

    socket.socket.connect = no_external
    shop = Platform(87, ['31','32'])
    remote = home/'synthetic-platform.json'
    args = ['images','replace-sku-images','--profile',PROFILE,'--store-config',str(home/'store.json'),
            '--product-id','42']
    if remote.is_file():
        previous = json.loads(remote.read_bytes())
        shop.detail, shop.edits = previous['detail'],previous['edits']
    def get(skill, url, params=None):
        if url.endswith('/venderinfo'):
            return {'success':True,'data':IDENTITY}
        if url.endswith('/product-apply/{applyId}'):
            return {'data':shop.detail}
        return shop.get(skill,url,params)

    def image_command(tail):
        output = io.StringIO()
        with patch.object(sys,'argv',args+tail), redirect_stdout(output):
            rc = images.main()
        result = json.loads(output.getvalue())
        assert rc == 0, result
        return result

    with patch.object(images.cli,'get',side_effect=get), patch.object(images.cli,'upload',side_effect=shop.upload), \
            patch.object(images.cli,'command_edit_product',side_effect=shop.command_edit_product):
        if stage == 'submit':
            sl = linker.sl
            sl.profiles_dir().mkdir(parents=True,exist_ok=True)
            atomic_json(sl.profiles_dir()/(PROFILE+'.json'), {})
            sl.save_registry({'profiles':{PROFILE:{'shopName':'fixture','venderId':'99','shopId':'77','aliases':['演示店']}}})
            def venderinfo(argv, **kwargs):
                assert '/rest/sp-seller/v0/venderinfo' in argv and '--profile='+PROFILE in argv
                return 0,json.dumps({'success':True,'data':IDENTITY})
            with patch.object(sys,'argv',['linker','ensure-shop','--shop','演示店','--no-auth']), \
                    patch.object(sl,'find_jdo',return_value=sys.executable), patch.object(sl,'run_jdo',side_effect=venderinfo):
                # linker.main configures UTF-8 on the output stream.
                ready = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
                with redirect_stdout(ready):
                    assert linker.main() == 0
                ready.flush()
                connected = json.loads(ready.buffer.getvalue())
                ready.close()
                assert connected['status']=='ready' and connected['shopId']=='77'
            atomic_json(home/'store.json',{'store':connected})
            Image.new('RGB',(600,600),'blue').save(home/'blue.jpg')
            atomic_json(home/'images.json',{sid:'blue.jpg' for sid in shop.ids})
            assert image_command(['--check-only','--images',str(home/'images.json')])['status']=='eligible'
            shop.lose_response = True
            try:
                image_command(['--confirm','REPLACE_SKU_IMAGES','--images',str(home/'images.json')])
            except TimeoutError:
                pass
            else:
                raise AssertionError('Lost-response fixture did not interrupt the original task')
            assert shop.edits == shop.uploads == 1
            atomic_json(remote,{'detail':shop.detail,'edits':shop.edits})
        else:
            result = image_command(['--reconcile'])
            assert result['status'] == 'verified' and result['skuMatches'] == {'31':True,'32':True}
            assert shop.edits == 1 and shop.uploads == 0
            print(json.dumps({'deliveredSkuSlots':sum(result['skuMatches'].values()), 'shopWrites':shop.edits,
                              'replayedWrites':0, 'paidModelCalls':0, 'duplicateConfirmations':0,
                              'merchantTechnicalHints':0, 'dialogue':'scripted synthetic host'}))


def main():
    if len(sys.argv) == 4:
        execute_stage(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3])
        return
    sys.path.insert(0,str(ROOT))
    from heideng_merchant.safety import clean_environment
    with tempfile.TemporaryDirectory(prefix='merchant-pr-journey-') as tmp:
        home = Path(tmp)
        state = home/'state'
        env = clean_environment(home)
        env.update(HEIDENG_MERCHANT_HOME=str(state), JINGMAI_LINKER_HOME=str(state/'linker'),
                   JDO_HOME=str(state/'cli-home/.jdo-cli'), PYTHONIOENCODING='utf-8')
        def run(argv):
            return subprocess.check_output([sys.executable,'-I','-B',*map(str,argv)], cwd=home,env=env,
                                           text=True,encoding='utf-8',timeout=120)
        installed = json.loads(run([ROOT/'install.py','--home',home,'--state',state,'--host','workbuddy',
                                    '--offline','--no-auto-update']))
        assert installed['version'] == (ROOT/'VERSION').read_text().strip()
        target = home/'.workbuddy/skills/heideng-ops-agent-merchant'
        run([__file__,target,home,'submit'])
        tasks = json.loads(run([target/'scripts/merchant.py','--state',state,'task-context','--shop-id','77',
                                '--vender-id','99','--goal','sku-edit','--product-id','42']))
        assert len(tasks['tasks']) == 1, tasks
        print(run([__file__,target,home,'recover']).strip())


if __name__ == '__main__':
    main()
