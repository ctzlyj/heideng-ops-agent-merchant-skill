"""Install the checked-out PR into an isolated WorkBuddy and resume a lost edit response.

The harness scripts host decisions and simulates the shop/media services. Connection,
eligibility, upload deduplication, task discovery and readback use the installed code.
Natural-language understanding and merchant-supplied technical hints need a real host.
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
    from heideng_merchant import fee_consent, mature_image
    from heideng_merchant.safety import atomic_json
    from test_category_sku_edit import Platform

    def no_external(*args, **kwargs):
        raise AssertionError('The merchant journey attempted an external connection')

    socket.socket.connect = no_external
    shop = Platform(87, ['31','32'])
    remote = home/'synthetic-platform.json'
    product_id = '42'
    counters = {'paidModelCalls':0,'feePrompts':0, 'merchantInputPrompts':0}
    if remote.is_file():
        previous = json.loads(remote.read_bytes())
        shop.detail, shop.edits, shop.uploads = previous['detail'],previous['edits'],previous['uploads']
        counters.update(previous['counters'])
        task = json.loads((home/'selected-task.json').read_bytes())
        product_id = task['productId']
    writes_before = shop.edits
    args = ['images','replace-sku-images','--profile',PROFILE,'--store-config',str(home/'store.json'),
            '--product-id',str(product_id)]
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
            patch.object(images.cli,'command_edit_product',side_effect=shop.command_edit_product), \
            patch.object(mature_image.MerchantImageClient,'edit',side_effect=AssertionError('unexpected paid model call')) as paid, \
            patch.object(fee_consent,'_ask_merchant',side_effect=AssertionError('unexpected fee prompt')) as fees, \
            patch('builtins.input',side_effect=AssertionError('unexpected input request')) as inputs:
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
        else:
            result = image_command(['--reconcile'])
            assert result['status'] == 'verified' and result['skuMatches'] == {'31':True,'32':True}
            assert result['otherFieldsMatch'] and result['resumedOriginal']
            assert shop.edits == writes_before and shop.uploads == previous['uploads']
        counters['paidModelCalls'] += paid.call_count
        counters['feePrompts'] += fees.call_count
        counters['merchantInputPrompts'] += inputs.call_count
        if stage == 'submit':
            atomic_json(remote,{'detail':shop.detail, 'edits':shop.edits, 'uploads':shop.uploads, 'counters':counters})
        else:
            print(json.dumps({'deliveredSkuSlots':sum(result['skuMatches'].values()), 'editSubmissions':shop.edits,
                              'mediaUploads':shop.uploads, 'replayedWrites':shop.edits-writes_before, **counters,
                              'merchantTechnicalHints':None, 'host':'scripted synthetic host'}))


def run_collection_example(run, target, home, state):
    from hashlib import sha256
    from shlex import split
    from openpyxl import Workbook

    out = home / '采集任务'
    out.mkdir()
    source = home / '商品 来源表.xlsx'
    wb = Workbook()
    wb.active.append(['synthetic'])
    wb.active.append([None, 'Synthetic product', '10000000000001'] + [None] * 9 +
                     ['https://item.jd.com/10000000000001.html'])
    wb.save(source)
    wb.close()
    registry = json.loads((target / 'registry.json').read_bytes())
    collection = next(item for item in registry['capabilities'] if item['id'] == 'collection')
    example = split(collection['merchantCommands'][0])
    values = {'<output>': str(out), '<source.xlsx>': str(source)}
    report = json.loads(run([target/'scripts/merchant.py', '--state', state, *(values.get(arg, arg) for arg in example)]))
    assert report['sha256'] == sha256(source.read_bytes()).hexdigest() and report['sourceProducts'] == 1
    manifests = list((state/'mature/collection/batches').glob('*/keyword_tasks.json'))
    assert len(manifests) == 1
    assert '10000000000001' in manifests[0].read_text(encoding='utf-8')
    return report['sourceProducts']


def main():
    if len(sys.argv) == 4:
        if sys.argv[3] == 'shop-copy':
            import unittest
            target=Path(sys.argv[1])
            sys.path[:0]=[str(target),str(ROOT)]
            from tests import test_shop_copy_entry as cases
            from tests.test_shop_copy_batch import BatchCopyTests
            from tests import test_shop_copy_repair
            from heideng_merchant import owned_product_copy, shop_copy_batch, shop_copy_repair
            for module in (owned_product_copy, shop_copy_batch, shop_copy_repair):
                assert Path(module.__file__).resolve().is_relative_to(target)
            cases.ROOT=target
            def no_network(*args, **kwargs):
                raise AssertionError('the two-store fixture attempted a network connection')
            with patch.object(socket.socket, 'connect', no_network):
                loader=unittest.defaultTestLoader
                suite=unittest.TestSuite([loader.loadTestsFromModule(cases),loader.loadTestsFromTestCase(BatchCopyTests),
                                          loader.loadTestsFromModule(test_shop_copy_repair)])
                result=unittest.TextTestRunner().run(suite)
            assert result.wasSuccessful()
            print(json.dumps({'installedTwoStoreScenarios':result.testsRun, 'realShopWrites':0}))
            return
        execute_stage(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3])
        return
    sys.path.insert(0,str(ROOT))
    from heideng_merchant.safety import clean_environment
    with tempfile.TemporaryDirectory(prefix='merchant-pr-journey-') as tmp:
        home = Path(tmp).resolve()
        state = home/'state'
        env = clean_environment(home)
        env.update(HEIDENG_MERCHANT_HOME=str(state), JINGMAI_LINKER_HOME=str(state/'linker'),
                   JDO_HOME=str(state/'cli-home/.jdo-cli'), PYTHONIOENCODING='utf-8')
        def run(argv):
            proc = subprocess.run([sys.executable,'-I','-X','utf8','-B',*map(str,argv)], cwd=home,env=env,
                                  capture_output=True,text=True,encoding='utf-8',timeout=120)
            if proc.returncode:
                raise RuntimeError(f'Isolated merchant command failed ({proc.returncode}): {proc.stdout} {proc.stderr}')
            return proc.stdout
        installed = json.loads(run([ROOT/'install.py','--home',home,'--state',state,'--host','workbuddy',
                                    '--offline','--no-auto-update']))
        assert installed['version'] == (ROOT/'VERSION').read_text().strip()
        target = home/'.workbuddy/skills/heideng-ops-agent-merchant'
        receipt = json.loads((target/'.merchant-install.json').read_bytes())
        assert receipt['sourceManifestSha256'] == receipt['files']['package-manifest.json']
        assert 'archiveSha256' not in receipt
        run([__file__,target,home,'submit'])
        tasks = json.loads(run([target/'scripts/merchant.py','--state',state,'task-context','--shop-id','77',
                                '--vender-id','99','--goal','sku-edit','--product-id','42']))
        assert len(tasks['tasks']) == 1, tasks
        task = tasks['tasks'][0]
        assert task['kind'] == 'sku-edit' and str(task['productId']) == '42'
        (home/'selected-task.json').write_text(json.dumps(task), encoding='utf-8')
        result = json.loads(run([__file__,target,home,'recover']))
        sys.path.insert(0,str(ROOT/'tests'))
        from run_gallery_journey import run_journey
        result['singleSkuPilot'] = run_journey(run,target,home,state)
        result['collectionExampleProducts'] = run_collection_example(run, target, home, state)
        help_text = run([target/'scripts/merchant.py','--state',state,'run','shop-copy','--','--help'])
        assert all(action in help_text for action in ('submit-one','repair-sku-codes','batch-run','batch-resume','batch-stop'))
        result['ownedShopCopy'] = json.loads(run([__file__,target,home,'shop-copy']))
        print(json.dumps(result))


if __name__ == '__main__':
    main()
