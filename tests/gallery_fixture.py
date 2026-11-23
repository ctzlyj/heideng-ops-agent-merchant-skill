"""A synthetic product whose first, detail and public positions share an image."""
import json
from pathlib import Path


def detail(shared='shared'):
    def group(key, urls):
        return {'uuid': key, 'imageInfoList': [{'orderSort': n, 'imgUrl': url} for n, url in enumerate(urls, 1)]}
    return {'productInfo': {'productId': 41, 'categoryDetail': {'lastCategoryId': 8}},
            'skuList': [{'skuId': 301, 'priceInfo': {'jdPrice': 15}, 'saleAttrs': [{'dim': 1, 'attrValues': 'blue'}]},
                        {'skuId': 302, 'priceInfo': {'jdPrice': 17}, 'saleAttrs': [{'dim': 1, 'attrValues': 'red'}]}],
            'material': {'mainImages': [group('blue', [shared, 'b-detail', shared]),
                                        group('red', [shared, 'r-detail']),
                                        group('0000000000', [shared])]}}


def apply_patch(live, body_path):
    body = json.loads(Path(body_path).read_bytes())
    groups = {group['uuid']: group for group in live['material']['mainImages']}
    for operation in body['patchOperationList']:
        for index, item in enumerate(json.loads(operation['value'])['value']):
            props = {p['key']: p['value'] for p in item['properties']}
            assert props['orderSort'] == str(index + 1)
            groups[props['colorId']]['imageInfoList'][index]['imgUrl'] = props['imgUrl']
    return {'data': {'applyId': 41}}
