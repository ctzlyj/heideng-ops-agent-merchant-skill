"""Identify accepted shop media by its actual platform name and the uploaded bytes."""
from hashlib import sha256
import io
from pathlib import Path
import re


def platform_image_name(name):
    if sum(1 if c.isascii() else 2 for c in name) <= 64:
        return name
    return 'image-' + sha256(name.encode()).hexdigest()[:32] + Path(name).suffix.lower()


class UploadImage(io.BytesIO):
    """The mature upload client needs a name and immutable bytes; PIL can read the same stream."""

    def __init__(self, name, data):
        super().__init__(data)
        self.name = name

    def read_bytes(self):
        return self.getvalue()


def matching_original(url, expected, size):
    import requests
    if not re.fullmatch(r'jfs/[a-zA-Z0-9_./-]+', url) or '..' in url.split('/'):
        return False
    hashed, length = sha256(), 0
    with requests.get('https://img10.360buyimg.com/imgzone/' + url, timeout=30, stream=True,
                      allow_redirects=False) as response:
        if response.status_code != 200:
            return False
        for chunk in response.iter_content(65536):
            length += len(chunk)
            if length > size:
                return False
            hashed.update(chunk)
    return length == size and hashed.hexdigest() == expected


def named_images(cli, intent, name):
    candidates, seen, page = {}, set(), 1
    while True:
        result = cli.get('jdo-product-material', '/rest/sp-product/v0/media-zones/{zoneId}/images',
                         {'zoneId': intent['zoneId'], 'categoryId': intent['categoryId'], 'imgName': Path(name).stem,
                          'page': page, 'pageSize': 50})
        rows = result.get('data')
        if not isinstance(rows, list):
            return None
        if any(not isinstance(row, dict) for row in rows):
            return None
        ids = {str(row.get('imgId')) for row in rows}
        if rows and ids <= seen:
            return None
        seen.update(ids)
        for row in rows:
            url = str(row.get('imgUrl') or '')
            if (row.get('imgName') == name and str(row.get('categoryId')) == str(intent['categoryId'])
                    and row.get('imgId') and 'jfs/' in url):
                candidates[url[url.index('jfs/'):]] = row
        total = (result.get('paginationData') or {}).get('totalItems')
        if not rows or (len(seen) >= int(total) if total is not None else len(rows) < 50):
            break
        page += 1
    return candidates


def reconcile_image(cli, old, intent, shop):
    """Absence, ambiguity and mismatches leave the original submission pending."""
    if (old.get('shopIdentity') and old['shopIdentity'] != shop
            or any(str(old.get(k)) != str(intent[k]) for k in ('zoneId', 'categoryId', 'sha256', 'uploadSha256'))
            or old.get('name') != intent['name']):
        return None
    canonical = intent['platformName']
    if old.get('platformName', canonical) != canonical:
        return None
    names = {canonical} if old.get('platformName') else {canonical, intent['name']}
    candidates = {}
    for name in sorted(names):
        found = named_images(cli, intent, name)
        if found is None:
            return None
        candidates.update(found)
    matches = [(url, row) for url, row in candidates.items()
               if row.get('imgSize') in (None, intent['uploadBytes'], str(intent['uploadBytes']))
               and matching_original(url, intent['uploadSha256'], intent['uploadBytes'])]
    if len(matches) != 1:
        return None
    url, row = matches[0]
    return {**old, **intent, 'platformName': row['imgName'], 'imgUrl': url, 'status': 'succeeded', 'imgId': str(row['imgId']),
            'reconciled': True, 'originalStatus': old.get('status')}


def media_space(api):
    zones = api.get('jdo-product-material', '/rest/sp-product/v0/media-zones').get('data') or []
    zone = next((z['zoneId'] for z in zones if z.get('zoneType') == 1), None)
    if zone is None:
        raise ValueError('未找到本店图片空间')
    cats = api.get('jdo-product-material', '/rest/sp-product/v0/media-zones/{zoneId}/categories',
                   {'zoneId':zone, 'page':1, 'pageSize':100}).get('data') or []
    cat = next((c['categoryId'] for c in cats if c.get('categoryName') == '我的本地文件' or c.get('status') == 1), None)
    if cat is None:
        raise ValueError('本店图片空间无可用目录')
    return zone, cat
