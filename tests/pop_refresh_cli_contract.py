"""Exercise gallery scope and incomplete progress through installed business entrypoints."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def run(root, job_entry=None, report_entry=None):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        if (root/'scripts/merchant.py').is_file():
            state = base/'merchant-state'
            skills = base/'skills'
            subprocess.run([sys.executable,str(root/'install.py'),'--state',str(state),'--skills-dir',str(skills),
                            '--offline','--no-auto-update'], check=True, capture_output=True, timeout=180)
            wrapper = [sys.executable,str(skills/'heideng-ops-agent-merchant/scripts/merchant.py'),'--state',str(state),'run']
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
        print(json.dumps({'targetLinks':len(scope),'samplesReused':1,'unresolvedUploads':1,'verified':0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--job-entry-json',type=json.loads)
    parser.add_argument('--report-entry-json',type=json.loads)
    args = parser.parse_args()
    run(args.root.resolve(), args.job_entry_json, args.report_entry_json)
