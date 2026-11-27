"""Exercise gallery scope and incomplete progress through installed business entrypoints."""
import argparse
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import Mock, patch

from openpyxl import load_workbook


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def product(pid, index, count):
    def gallery(urls):
        return {'uuid':'0000000000', 'imageInfoList':[
            {'orderSort':pos, 'imgUrl':url} for pos, url in enumerate(urls, 1)]}

    urls = [f'jfs/fixture/{pid}/source-{pos}.png' for pos in range(1, count + 1)]
    if index < 4:
        # Four protected covers already equal a URL that will occur in the uploaded set.
        urls[0] = f'jfs/fixture/{pid}/result-2.png'
    if index == 0:
        # One uploaded asset serves two independently requested physical slots.
        urls[2] = urls[1]
    rect_count = 0 if index == 0 else 2 if index == 1 else 1
    rectangles = [gallery([f'jfs/fixture/{pid}/long-{n}.png' for n in range(rect_count)])] if rect_count else []
    return {'productInfo':{'productId':pid,'productName':('餐具' if index % 2 else '收纳件')+str(pid),
                           'productStatus':103,'categoryDetail':{'lastCategoryId':7}},
            'skuList':[{'skuId':10000+pid,'saleAttrs':[],'priceInfo':{'jdPrice':12}}],
            'material':{'mainImages':[gallery(urls)],'rectangleImages':rectangles}}


def verify_scope(work, package, scripts, report_entry):
    """Run the real independent verifier with only its read-only platform transport substituted."""
    sys.path[:0] = [str(scripts), str(package)]
    import _common as common
    import verify

    sizes = (5, 5, 7, 7, 7, 7, 6, 6, 7, 7)
    before = {101+i:product(101+i, i, count) for i, count in enumerate(sizes)}
    after = deepcopy(before)
    plan = common.build_plan(before, order=list(before), scopes=['main'], positions=[2,3,4,5])
    assert len(plan['tasks']) == 39
    uploads = {key:{'status':'succeeded','imgUrl':task['currentUrl'].replace('/source-', '/result-')}
               for key, task in plan['tasks'].items()}
    for row in plan['products']:
        pid = row['productId']
        row['listStatus'] = 103
        common.save_json(work/'products'/str(pid)/'before-apply.json', before[pid])
        for image in after[pid]['material']['mainImages'][0]['imageInfoList'][1:5]:
            image['imgUrl'] = image['imgUrl'].replace('/source-', '/result-')
    # URLs/positions refer to the same images even if the platform reorders its array or enriches metadata.
    long_images = after[102]['material']['rectangleImages'][0]['imageInfoList']
    long_images.reverse()
    for image in long_images:
        image.update(imgUrl='https://img10.360buyimg.com/'+image['imgUrl'], width=900)
    common.save_json(work/'job.json', {'profile':'fixture','venderId':1,'shopName':'fixture','productIds':list(before)})
    common.save_json(work/'plan-batch.json', plan)
    common.save_json(work/'uploads.json', uploads)

    def get(skill, path, params):
        if path == '/rest/sp-seller/v0/venderinfo':
            return {'data':{'venderId':1, 'shopBaseInfo':{'shopName':'fixture','shopId':2}}}
        if path == '/rest/sp-product/v0/products':
            return {'data':[{'productId':pid, 'productStatus':103} for pid in before],
                    'paginationData':{'totalItems':len(before)}}
        if path == '/rest/sp-product/v0/product-apply/{applyId}':
            return {'data':after[params['applyId']]}
        raise AssertionError((skill, path))

    cli = Mock(spec_set=['get', 'mark_jdo_store_verified'])
    cli.get.side_effect = get
    def readback(expect_ok):
        with patch.object(common, 'connect', return_value=cli), redirect_stdout(StringIO()):
            code = 0
            try:
                verify.main(['verify.py', str(work)])
            except SystemExit as exc:
                code = exc.code
        rows = json.loads((work/'final-verification.json').read_bytes())
        assert (code == 0) == expect_ok, rows
        return rows

    def report(*options):
        result = subprocess.run([*report_entry, str(work), *options], check=True, capture_output=True, timeout=120)
        return json.loads(result.stdout) if options else (work/'batch-result.md').read_text(encoding='utf-8')

    rows = readback(True)
    assert set(rows) == {str(pid) for pid in before}
    for row in rows.values():
        evidence = row['mainSlotReadback']
        assert row['ok'] and row['pricesUnchanged'] and row['status'] == 103, row
        assert evidence['verified'] == 4 and {s['position'] for s in evidence['slots']} == {2,3,4,5}, evidence
    progress = report('--progress')
    counts, rectangles = progress['mainSlotReadback'], progress['rectangleReadback']
    assert (counts['requested'], counts['verified'], progress['finalVerifiedProducts']) == (40, 40, 10), progress
    assert (rectangles['unchangedProducts'], rectangles['unchangedSlots'], rectangles['absentProducts']) == (9, 10, 1)
    markdown = report()
    assert '本次授权 40 个主图位，已逐位核实换新 40 个' in markdown
    assert '9 个商品的 10 个长图位已核实未变' in markdown and '独立终验：10/10 通过' in markdown
    workbook = load_workbook(next(work.glob('*.xlsx')), read_only=True)
    try:
        headers, *data = workbook['优化结果'].values
        for label in ('授权主图位', '主图换新'):
            assert [row[headers.index(label)] for row in data] == [4]*10, (label, data)
        assert [row[headers.index('范围外3:4长图')] for row in data].count('已核实未变') == 9
        assert sum(row[headers.index('长图回读位数')] for row in data) == 10
    finally:
        workbook.close()

    after[102]['material']['rectangleImages'][0]['imageInfoList'][0]['imgUrl'] = 'jfs/fixture/changed-long.png'
    del after[103]['material']['rectangleImages']
    slots = after[104]['material']['mainImages'][0]['imageInfoList']
    slots[1]['imgUrl'] = slots[2]['imgUrl']  # real upload, wrong slot
    interrupted = next(row['positions'][1]['key'] for row in plan['products'] if row['productId'] == 105)
    uploads[interrupted] = {'status':'unknown'}
    common.save_json(work/'uploads.json', uploads)
    rows = readback(False)
    assert not any(rows[str(pid)]['ok'] for pid in (102,103,104,105)), rows
    assert rows['102']['rectangleReadback']['status'] == 'changed'
    assert rows['103']['rectangleReadback']['status'] == 'unverified'
    progress = report('--progress')
    counts, rectangles = progress['mainSlotReadback'], progress['rectangleReadback']
    assert (counts['requested'], counts['verified'], counts['unresolved']) == (40, 38, 2), counts
    assert (rectangles['changedProducts'], rectangles['unverifiedProducts']) == (1,1), rectangles
    assert progress['finalVerifiedProducts'] == 6
    markdown = report()
    assert '仍待核实 2 个' in markdown and '1 个商品的长图发生变化' in markdown

    # An existing pre-upgrade receipt can establish neither authorization coverage nor a protected long-image readback.
    for row in rows.values():
        row.pop('mainSlotReadback', None)
        row.pop('rectangleReadback', None)
    common.save_json(work/'final-verification.json', rows)
    legacy = report('--progress')
    assert legacy['mainSlotReadback']['productsPendingEvidence'] == 10, legacy
    assert legacy['mainSlotReadback']['verified'] in (0, None) and legacy['rectangleReadback']['unverifiedProducts'] == 10
    assert legacy['finalVerifiedProducts'] == 0 and '10 个商品缺少逐位终验回执' in report()


def run(root, job_entry=None, report_entry=None):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        package = root
        scripts = root/'scripts'
        if (root/'scripts/merchant.py').is_file():
            state = base/'merchant-state'
            skills = base/'skills'
            subprocess.run([sys.executable,str(root/'install.py'),'--state',str(state),'--skills-dir',str(skills),
                            '--offline','--no-auto-update'], check=True, capture_output=True, timeout=180)
            wrapper = [sys.executable,str(skills/'heideng-ops-agent-merchant/scripts/merchant.py'),'--state',str(state),'run']
            package = skills/'heideng-ops-agent-merchant'
            scripts = package/'mature/refresh/scripts'
            job_entry = [*wrapper,'image-refresh','--']
            report_entry = [*wrapper,'--entry','scripts/report.py','image-refresh','--']
        job_entry = job_entry or [sys.executable,str(root/'scripts/new_job.py')]
        report_entry = report_entry or [sys.executable,str(root/'scripts/report.py')]
        original = base/'copy-batch.json'
        shop = {'profile':'fixture', 'venderId':1, 'shopName':'fixture'}
        write(original, {'status':'batch-status','targetShop':shop,'rows':[
            {'sourceProductId':'8','targetProductId':p,'comparison':{'readbackView':'product'}} for p in ('41','42')]})
        work = base/'images'
        subprocess.run([*job_entry,str(work),'--profile','fixture','--vender-id','1','--shop-name','fixture',
                        '--main-selection','per-link','--copy-batch-report',str(original)],
                       check=True, capture_output=True, timeout=120)
        scope = json.loads((work/'job.json').read_bytes())['mainSelection']['sourceByProduct']
        assert scope == {'41':'8','42':'8'}, scope
        write(work/'plan-batch.json', {'tasks':{'one':{'productId':41},'two':{'productId':42}}})
        write(work/'internal-generation.json', {'one':{'status':'succeeded','reusedSample':{'key':'approved'}}})
        write(work/'uploads.json', {'one':{'status':'unknown'}})
        result = subprocess.run([*report_entry,str(work),'--progress'], capture_output=True, check=True, timeout=120)
        receipt = json.loads(result.stdout)
        assert receipt['approvedSamplesReused'] == 1 and receipt['newImagesSucceeded'] == 0, receipt
        assert receipt['unresolvedUploads'] == 1 and receipt['finalVerifiedProducts'] == 0, receipt
        verify_scope(base/'readback', package, scripts, report_entry)
        print(json.dumps({'targetLinks':len(scope),'samplesReused':1,'unresolvedUploads':1,'verified':0,
                          'verifiedScope':'40/40','protectedLongImageProducts':9,'assets':39}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--job-entry-json',type=json.loads)
    parser.add_argument('--report-entry-json',type=json.loads)
    args = parser.parse_args()
    run(args.root.resolve(), args.job_entry_json, args.report_entry_json)
