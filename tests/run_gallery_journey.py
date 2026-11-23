"""Continue from a local preview into one SKU slot, including a lost PATCH reply."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch


SHARED = 'https://img10.360buyimg.com/imgzone/jfs/fixture/shared.png'


def run_journey(run, target, home, state):
    from PIL import Image

    connected = json.loads((home/'store.json').read_bytes())['store']
    work = home/'single-SKU'
    work.mkdir()
    Image.new('RGB',(90,90),'navy').save(work/'base.png')
    Image.new('RGBA',(8,12),'gold').save(work/'art.png')
    plan = {'target': {'shopId':str(connected['shopId']), 'venderId':str(connected['venderId']),
                       'productId':'41', 'skuId':'301', 'galleryUrl':SHARED},
            'source':{'file':'base.png'}, 'layers':[{'file':'art.png','box':[20,25,28,37]}],
            'compareBox':[15,20,35,45]}
    spec = work/'design.json'
    spec.write_text(json.dumps(plan),encoding='utf-8')
    preview = json.loads(run([target/'scripts/merchant.py','--state',state,'preview-overlay','--plan',spec]))
    assert preview['target'] == plan['target'] and preview['status'] == 'local-preview'
    assert preview['paidRequests'] == preview['platformWrites'] == 0
    assert Path(preview['comparisonPath']).is_file()
    (work/'handoff.json').write_text(json.dumps(preview),encoding='utf-8')
    run([__file__,target,home,'submit'])
    return json.loads(run([__file__,target,home,'recover']))


def execute(target, home, stage):
    sys.path[:0] = [str(target),str(target/'mature/listing/scripts'),str(Path(__file__).parent)]
    from gallery_fixture import apply_patch, detail
    from heideng_merchant import fee_consent, mature_image
    from heideng_merchant.mature_runtime import source_path
    from heideng_merchant.safety import atomic_json, file_sha
    import image_patch_update as images

    assert Path(images.__file__).resolve() == source_path('images', package_root=target)[0]
    work = home/'single-SKU'
    preview = json.loads((work/'handoff.json').read_bytes())
    store = json.loads((home/'store.json').read_bytes())['store']
    handoff = preview['target']
    assert handoff['shopId'] == str(store['shopId']) and handoff['venderId'] == str(store['venderId'])
    remote_path = work/'simulated-store.json'
    initial = detail(SHARED)
    remote = json.loads(remote_path.read_bytes()) if stage=='recover' else {
        'detail':deepcopy(initial), 'edits':0, 'uploads':0}

    def get(skill, url, params=None):
        if url.endswith('/venderinfo'):
            return {'data':{'venderId':store['venderId'],'shopBaseInfo':{
                'shopId':store['shopId'],'shopName':store['shopName'],'type':0,'status':1}}}
        if url.endswith('/product-apply/{applyId}'):
            assert str(params['applyId']) == handoff['productId']
            return {'data':deepcopy(remote['detail'])}
        if url.endswith('/media-zones'):
            return {'data':[{'zoneType':1,'zoneId':'z'}]}
        if url.endswith('/categories'):
            return {'data':[{'categoryId':12,'status':1}]}
        raise AssertionError(url)

    def upload(zone, category, image):
        assert file_sha(image) == preview['previewSha256'] == file_sha(Path(preview['previewPath']))
        remote['uploads'] += 1
        return {'imgUrl':'jfs/'+preview['previewSha256']}

    def publish(**kwargs):
        assert kwargs['method'] == 'PATCH' and kwargs['params']['applyId'] == handoff['productId']
        apply_patch(remote['detail'],kwargs['body_path'])
        remote['edits'] += 1
        atomic_json(remote_path,remote)
        raise TimeoutError('simulated lost reply after platform acceptance')

    def command(args):
        result = io.StringIO()
        argv = ['images','pilot-main-image','--profile',store['profile'],'--store-config',str(home/'store.json'),
                '--product-id',handoff['productId'],'--sku-id',handoff['skuId'],*args]
        with patch.object(sys,'argv',argv), redirect_stdout(result):
            status = images.main()
        assert status == 0, result.getvalue()
        return json.loads(result.getvalue())

    with patch.object(socket.socket,'connect',side_effect=AssertionError('unexpected external connection')), \
            patch.object(mature_image.MerchantImageClient,'edit',side_effect=AssertionError('unexpected paid edit')) as paid, \
            patch.object(fee_consent,'_ask_merchant',side_effect=AssertionError('unexpected fee prompt')), \
            patch.object(images.cli,'get',side_effect=get), patch.object(images.cli,'upload',side_effect=upload) as uploads, \
            patch.object(images.cli,'run_jdo_large',side_effect=publish) as edits:
        if stage == 'submit':
            preflight = command(['--check-only'])
            assert preflight['oldUrl'] == handoff['galleryUrl'] and preflight['affectedSkuIds'] == [handoff['skuId']]
            remote['preflightWrites'] = edits.call_count+uploads.call_count
            assert preflight['writes'] == remote['preflightWrites'] == 0
            try:
                command(['--confirm','PUBLISH_ONE_SKU_FIRST_IMAGE','--expected-url',preflight['oldUrl'],
                         '--image',preview['previewPath']])
            except TimeoutError:
                pass
            else:
                raise AssertionError('the lost reply must interrupt the submitting process')
            assert edits.call_count == uploads.call_count == 1 and paid.call_count == 0
            return

        recovered = command(['--reconcile'])
        assert recovered['status'] == 'verified-in-edit-detail' and recovered['reconciled']
        assert recovered['changedSlots'] == 1 and recovered['affectedSkuIds'] == [handoff['skuId']]
        assert recovered['consumerPageStatus'] == 'unchecked'
        assert remote['edits'] == remote['uploads'] == 1 and edits.call_count == uploads.call_count == paid.call_count == 0
        checked = deepcopy(initial)
        checked['material']['mainImages'][0]['imageInfoList'][0]['imgUrl'] = 'jfs/'+preview['previewSha256']
        assert checked == remote['detail']
        count = sum(len(group['imageInfoList']) for group in initial['material']['mainImages'])
        print(json.dumps({'targetSku':handoff['skuId'],'changedSlots':recovered['changedSlots'],'preservedSlots':count-1,
                          'preflightWrites':remote['preflightWrites'],'editSubmissions':remote['edits'],'mediaUploads':remote['uploads'],
                          'paidRequests':preview['paidRequests']+paid.call_count,'recoveryWrites':edits.call_count+uploads.call_count,
                          'consumerPageStatus':recovered['consumerPageStatus']}))


if __name__=='__main__':
    execute(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3])
