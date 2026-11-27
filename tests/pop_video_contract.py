"""Exercise local POP video composition, reviewed handoff and tamper detection via a real CLI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw


def run_contract(state, *, prefix=None, merchant=None):
    env = dict(os.environ, HEIDENG_MERCHANT_HOME=str(state), PYTHONUTF8='1')
    def call(argv, codes=(0,)):
        proc = subprocess.run(argv, env=env, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=120)
        assert proc.returncode in codes, (proc.returncode, proc.stdout[-600:], proc.stderr[-800:])
        return proc.stdout
    if merchant:
        skills = state/'skills'
        call([sys.executable, str(merchant/'install.py'), '--offline', '--no-auto-update',
              '--state', str(state), '--skills-dir', str(skills)])
        prefix = [sys.executable, str(skills/'heideng-ops-agent-merchant/scripts/merchant.py'),
                  '--state', str(state), 'run', 'video-handoff', '--']
    if prefix is None:
        prefix = [sys.executable, str(Path(__file__).resolve().parents[1]/'scripts/pop_video.py')]
    def action(argv, codes=(0,)):
        return json.loads(call(prefix + list(map(str, argv)), codes))

    package = state/'package'
    package.mkdir()
    manifest = package/'manifest.json'
    manifest.write_text('{"title":"synthetic","mainImages":["front.png","back.png"]}', encoding='utf-8')
    for name, color in [('front.png','orange'),('back.png','blue')]:
        img = Image.new('RGB', (640, 800), 'white')
        ImageDraw.Draw(img).rectangle((100, 80, 520, 670), fill=color)
        img.save(package/name)
    original = manifest.read_bytes()
    args = ['compose-local',package,'--image','front.png','--image','back.png','--run-id','sample']
    candidate = action(args)
    assert candidate['status'] == 'needs-visual-review' and not candidate['manifestWritten']
    assert candidate['width'] == candidate['height'] == 720 and candidate['durationSecondsExact'] >= 5
    assert not candidate['bindable'] and not candidate['voiceReviewRequired']
    assert candidate['platformWrites'] == 0
    assert action(args)['replayed'] and manifest.read_bytes() == original
    metadata = state/'synthetic-review.json'
    review = {'pass':True,'reviewer':'synthetic-fixture','videoSHA256':candidate['videoSha256'],
              'coverSHA256':candidate['coverSha256']}
    meta = {'mode':'material','label':'synthetic slideshow','bindable':True,'voiceReviewRequired':False,
            'qc':{'automatic':{'pass':True}, 'manual':dict(review,videoSHA256='0'*64)}}
    metadata.write_text(json.dumps(meta), encoding='utf-8')
    args = ['publish',package,'--run-id','sample','--video',package/candidate['video'],
            '--cover',package/candidate['cover'],'--metadata',metadata]
    call(prefix+list(map(str,args)), (1,2))
    assert manifest.read_bytes() == original
    meta['qc']['manual'] = review
    metadata.write_text(json.dumps(meta), encoding='utf-8')
    assert action(args)['ok']
    assert action(args)['replayed']
    folder = action(['verify-handoff',package])
    assert action(['verify-handoff',manifest]) == folder
    assert folder['filesVerified'] and folder['visualReview'] == folder['technicalReview'] == 'passed'
    assert folder['platformWrites'] == 0
    row = json.loads(manifest.read_text(encoding='utf-8'))['video']
    Image.new('RGB',(720,720),'green').save(package/row['coverLocalPath'])
    damaged = action(['verify-handoff',manifest], (2,3))
    assert not damaged['ok'] and not damaged['filesVerified']
    print(json.dumps({'candidate':'needs-visual-review','mismatchedReviewRejected':True,
                      'verifiedDirectoryAndManifest':True,'tamperedCoverRejected':True,'writes':0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry-json', type=json.loads)
    parser.add_argument('--merchant-root', type=Path)
    options = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        prefix = [arg.replace('{state}',temp) for arg in options.entry_json] if options.entry_json else None
        run_contract(Path(temp), prefix=prefix, merchant=options.merchant_root)
