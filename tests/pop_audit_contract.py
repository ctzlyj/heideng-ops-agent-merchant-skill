"""Synthetic GET transport. Exercise the real audit parser, pagination and on-disk receipt."""
import argparse
from collections import Counter
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from zipfile import ZipFile


class SyntheticShop:
    def __init__(self, products=24, delay=0):
        self.products = list(range(1001, 1001 + products))
        self.skus = [{'skuId': p * 10 + n, 'productId': p, 'status': 103, 'skuName': 'sample'}
                     for p in self.products for n in range(5)]
        self.delay = delay
        self.events = []
        self.material_skus = set()
        self.lock = threading.Lock()

    def get(self, _skill, url, params=None):
        start = time.perf_counter()
        if self.delay:
            time.sleep(self.delay)
        kind = url.rsplit('/', 1)[-1]
        if kind == 'venderinfo':
            result = {'data': {'venderId': '99', 'shopBaseInfo': {'type': 0, 'status': 1, 'shopName': 'synthetic', 'shopId': '88'}}}
        elif kind == '{productId}':
            assert params['productId'] in self.products
            result = {'data': {'productInfo': {'productId':params['productId']},
                               'skuList':[r for r in self.skus if r['productId']==params['productId']]}}
        elif kind == 'sku-materials':
            ids = params['skuIds']
            with self.lock:
                self.material_skus.update(ids)
            result = {'data': [{'skuId': sku, 'materials': []} for sku in ids]}
        else:
            if kind == 'products':
                rows = [{'productId': p, 'productStatus': 103} for p in self.products
                        if p in params.get('productIdList', self.products)]
            elif kind == 'skus':
                rows = [r for r in self.skus if r['productId'] in params['productIdList']]
            elif kind == 'health-infos':
                rows = [dict(r, healthScore=93, improvementList=[]) for r in self.skus]
            else:
                raise AssertionError('unexpected endpoint: ' + kind)
            page, size = int(params['page']), int(params['pageSize'])
            result = {'data': rows[(page-1)*size:page*size],
                      'paginationData': {'totalItems': len(rows), 'currentPage': page}}
        with self.lock:
            self.events.append((kind, start, time.perf_counter()))
        return result


def exercise(agent, *, scoped=True, products=24, delay=0):
    fixture = SyntheticShop(products, delay)
    targets = (1001, 1003)
    with tempfile.TemporaryDirectory() as output:
        args = ['audit-pop-coverage', '--expected-shop-name', 'synthetic',
                '--profile', 'synthetic', '--output-dir', output]
        if scoped:
            for product in targets:
                args.extend(['--target-spu-id', str(product)])
        stdout = io.StringIO()
        with patch.object(agent.JdoClient, '_get', side_effect=fixture.get), \
             patch.object(agent.JdoClient, '_run', side_effect=AssertionError('external CLI forbidden')), \
             redirect_stdout(stdout):
            assert agent.main(args) == 0
        delivered = time.perf_counter()
        receipt = json.loads(stdout.getvalue())
        report = json.loads(Path(receipt['report']).read_text(encoding='utf-8'))
        rows = [row for row in report['rows'] if int(row['productId']) in targets]
        expected = {r['skuId'] for r in fixture.skus if r['productId'] in targets}
        assert len(rows) == len(expected) == 10
        assert {int(row['skuId']) for row in rows} == expected
        assert all(row['slots']['white']['state'] == 'missing' for row in rows)
        assert report['writesPerformed'] is False
        if scoped:
            assert fixture.material_skus == expected
            assert len(report['rows']) == 10 and report['scope'] == 'selected'
        calls = dict(sorted(Counter(event[0] for event in fixture.events).items()))
        return {'targetSkus': len(rows), 'auditedSkus': len(report['rows']), 'calls': calls,
                'getSumSeconds': round(sum(e-s for _, s, e in fixture.events), 4),
                'firstGet': min(s for _, s, _ in fixture.events), 'lastGet': max(e for _, _, e in fixture.events),
                'receipt': delivered}


def exercise_entry(prefix):
    """Pass the real entry argv; {state} is an isolated test home. Only GETs can succeed."""
    with tempfile.TemporaryDirectory() as output:
        state = Path(output)
        tools = state/'tools'
        tools.mkdir()
        program = f"import runpy;runpy.run_path({str(Path(__file__).resolve())!r})['fixture_cli']()"
        if os.name == 'nt':
            from pip._vendor.distlib import scripts
            arch = '64-arm' if platform.machine().lower() == 'arm64' else ('64' if sys.maxsize > 2**32 else '32')
            launcher = Path(scripts.__file__).with_name('t' + arch + '.exe').read_bytes()
            package = io.BytesIO()
            with ZipFile(package, 'w') as archive:
                archive.writestr('__main__.py', program)
            cli = tools/'fixture.exe'
            cli.write_bytes(launcher + ('#!"' + sys.executable + '"\n').encode() + package.getvalue())
        else:
            cli = tools/'fixture'
            cli.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -c ' +
                           shlex.quote(program) + ' "$@"\n', encoding='utf-8')
            cli.chmod(0o755)
        (tools/'official.json').write_text(json.dumps({'root': 'tools', 'executable': cli.name,
            'executableSha256': hashlib.sha256(cli.read_bytes()).hexdigest()}), encoding='utf-8')
        args = [x.replace('{state}', output) for x in prefix] + ['audit-pop-coverage',
                '--target-spu-id', '1001', '--target-spu-id', '1003', '--profile', 'synthetic',
                '--expected-shop-name', 'synthetic', '--output-dir', output]
        env = dict(os.environ, JDO_CLI_PATH=str(cli), HEIDENG_MERCHANT_HOME=output, PYTHONUTF8='1')
        proc = subprocess.run(args, env=env, capture_output=True, text=True, encoding='utf-8', timeout=120)
        assert proc.returncode == 0, (proc.returncode, proc.stdout[-500:], proc.stderr[-700:])
        receipt = json.loads(proc.stdout)
        report = json.loads(Path(receipt['report']).read_text(encoding='utf-8'))
        assert report['scope'] == 'selected' and report['writesPerformed'] is False
        assert {int(row['skuId']) for row in report['rows']} == {
            pid * 10 + n for pid in (1001, 1003) for n in range(5)}
        assert report['onlineSkuCount'] == report['materialDeficitSkuCount'] == 10
        command = [x.replace('{state}', output) for x in prefix]
        exercise_delivery(state, command, env)
        print(json.dumps({'scope':'selected','targetSkuCount':10,'titleBatchRows':[5000,1],
                          'priorImportReconciledOnly':True,'parentSkus':5,
                          'repairReadback':['approved','pending','unknown'],'writes':0}))


def exercise_delivery(state, command, env):
    from openpyxl import load_workbook
    def action(argv, codes=(0,)):
        p = subprocess.run(command+list(map(str,argv)), env=env, capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=120)
        assert p.returncode in codes, (p.returncode,p.stdout[-800:],p.stderr[-800:])
        return json.loads(p.stdout)
    asset = Path(__file__).resolve().parents[1]
    if (asset/'mature/materials').exists():
        asset = asset/'mature/materials'
    template = asset/'assets/商品导入短标题模板.xlsx'
    def title_workbook(name, count):
        path = state/name
        workbook = load_workbook(template)
        sheet = workbook['Sheet1']
        sheet.delete_rows(3, max(1,sheet.max_row))
        for n in range(count):
            sheet.append([str(n+1),'家用整理收纳实用商品'])
        workbook.save(path)
        workbook.close()
        return path
    def prepare(path):
        return ['prepare-short-title-import','--source',path,'--output-dir',state]
    by_row = action(prepare(title_workbook('rows.xlsx',5001)))
    assert [b['rowCount'] for b in by_row['batches']] == [5000,1]
    assert all(b['byteCount']<=5*1024*1024 for b in by_row['batches'])
    oversized = title_workbook('bytes.xlsx',2)
    with ZipFile(oversized,'a') as archive:
        archive.writestr('unused/synthetic.bin',bytes(5*1024*1024))
    by_byte = action(prepare(oversized))
    chunk = by_byte['batches'][0]
    assert chunk['rowCount']==2 and chunk['byteCount']<5*1024*1024 and Path(chunk['path'])!=oversized
    original = state/'.state'/('title-import-'+chunk['sourceSha256'][:16]+'.json')
    original.parent.mkdir(exist_ok=True)
    original.write_text(json.dumps({'status':'unknown','sha256':chunk['sourceSha256']}),encoding='utf-8')
    assert action(prepare(oversized), (2,))['receiptPath']==str(original)
    plan = state/'plan'
    action(['plan-auto-maintain','--target-spu-id','1001','--include-full-score','--profile','synthetic',
            '--expected-shop-name','synthetic','--output-dir',plan])
    child = state/'child'/'.state'
    child.mkdir(parents=True)
    (child/'task.json').write_text(json.dumps({'jobs':{'1001':{'status':'completed'}}}))
    coverage = action(['coverage-summary','--parent-plan',plan/'自动维护计划.json','--child-dir',child.parent])
    assert coverage['targetSkuCount']==5 and not coverage['allApproved']
    assert coverage['remainingSlotCount']==coverage['targetSlotCount']>0
    assert coverage['counts']['approved']==0
    repair=state/'repair'
    (repair/'shared-bindings').mkdir(parents=True)
    ids=['10010','10011','10012']
    identity={'shopId':'88','shopName':'synthetic','venderId':'99'}
    (repair/'repair-scope.json').write_text(json.dumps({'shopIdentity':identity,'originals':{s:[] for s in ids}}))
    request={'skuIds':ids,'materialType':31,'body':{'skuMaterials':[
        {'skuId':int(s),'materials':[{'materialType':31,'order':1,'imageMaterial':{
            'skuImages':[{'index':1,'imgUrl':'jfs/new.png'}]}}]} for s in ids]}}
    (repair/'shared-bindings'/'batch.json').write_text(json.dumps({'request':request,'status':'unknown'}))
    result=action(['check-repair-status','--profile','synthetic-repair','--output-dir',repair],(2,))
    checked=json.loads(Path(result['resultFile']).read_text(encoding='utf-8'))
    assert checked['status']=='unknown' and not checked['writesPerformed']
    assert [r['status'] for r in checked['rows']]==['approved','pending','unknown']


def fixture_cli():
    args = sys.argv[1:]
    def arg(name):
        return args[args.index(name)+1]
    assert args[0] == 'invoke' and arg('--method') == 'GET' and arg('--profile') in ('synthetic','synthetic-repair')
    params = json.loads(arg('--params'))
    if arg('--url').endswith('sku-materials'):
        assert {int(s) // 10 for s in params['skuIds']} <= {1001, 1003}
    result=SyntheticShop().get(arg('--skill-id'), arg('--url'), params)
    if arg('--profile')=='synthetic-repair' and arg('--url').endswith('sku-materials') and 31 in params['materialTypes']:
        result={'data':[{'skuId':s,'materials':[{'materialType':31,'order':1,
            'status':4 if s==10010 else 3,'imageMaterial':{'skuImages':[{'index':1,'imgUrl':'jfs/new.png'}]}}]}
            for s in params['skuIds'] if s!=10012]}
    print(json.dumps({'success':True, **result}))


def main():
    started = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument('--scripts', type=Path, default=Path(__file__).resolve().parents[1]/'scripts')
    parser.add_argument('--products', type=int, default=24)
    parser.add_argument('--delay-ms', type=float, default=0)
    parser.add_argument('--whole-shop-baseline', action='store_true')
    parser.add_argument('--entry-json', help='Use a real subprocess entry; pass argv as a JSON list.')
    options = parser.parse_args()
    if options.entry_json:
        return exercise_entry(json.loads(options.entry_json))
    sys.path.insert(0, str(options.scripts.resolve()))
    import jd_material_agent as agent
    result = exercise(agent, scoped=not options.whole_shop_baseline,
                      products=options.products, delay=options.delay_ms / 1000)
    first, last, receipt = (result.pop(k) for k in ('firstGet', 'lastGet', 'receipt'))
    result.update(startupSeconds=round(first-started, 4), getWindowSeconds=round(last-first, 4),
                  receiptSeconds=round(receipt-started, 4))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
