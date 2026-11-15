"""Native edit-template captures and lossless local drafts; never submits a product."""
from __future__ import annotations
import copy
import hashlib
import json
import math
from decimal import Decimal
import re
import time
import uuid
from pathlib import Path
from . import VERSION
from .materials import MaterialService
from .operations import digest, _same_identity
from .products import ProductService, identifier, _category, _sku_source
from .safety import SafetyError, atomic_json, read_json, redact, safe_join, _SENSITIVE
from .verification import business_payload

SCHEMAS = '/rest/sp-product/v0/product-schemas'
MAX_SCHEMA_BYTES = 8 * 1024 * 1024  # Local parsing budget, not a platform restriction.
PRODUCT_IMAGES = {'WareSkuImg', 'LongImg'}
SKU_IMAGES = {'SkuMainImage', 'SkuRectangleImage'}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SafetyError('native-schema-duplicate-json-key')
        result[key] = value
    return result


def _nonfinite(_):
    raise SafetyError('native-schema-nonfinite-json-value')



def _lossless_float(token):
    value = float(token)
    if not math.isfinite(value) or Decimal(str(value)) != Decimal(token):
        raise SafetyError('native-schema-number-cannot-roundtrip-without-loss')
    return value


def _validate_logical_properties(schema):
    pending = [(schema, 0)]
    while pending:
        node, depth = pending.pop()
        if depth > 128:
            raise SafetyError('native-schema-exceeds-local-depth-budget')
        if isinstance(node, dict):
            logical_key = node.get('key')
            if isinstance(logical_key, str) and re.search(_SENSITIVE, logical_key, re.I):
                raise SafetyError('credentials-not-allowed-in-native-schema-properties')
            pending.extend((value, depth + 1) for value in node.values())
        elif isinstance(node, list):
            pending.extend((value, depth + 1) for value in node)
        elif isinstance(node, str) and node.lstrip().startswith(('{','[')):
            try:
                # Inspect embedded JSON without rewriting it or coercing its numbers.
                decoded = json.loads(node, object_pairs_hook=_unique_object,
                                     parse_float=str, parse_int=str, parse_constant=str)
            except ValueError:
                continue  # Ordinary text that merely starts with a bracket.
            except RecursionError:
                raise SafetyError('native-schema-exceeds-local-depth-budget') from None
            pending.append((decoded, depth + 1))


def parse_schema(response):
    templates = business_payload(response)
    if not isinstance(templates, list) or len(templates) != 1 or not isinstance(templates[0], str):
        raise SafetyError('one-explicit-native-edit-template-required')
    text = templates[0]
    if len(text) > MAX_SCHEMA_BYTES or len(text.encode('utf-8')) > MAX_SCHEMA_BYTES:
        raise SafetyError('native-schema-exceeds-local-memory-budget')
    try:
        schema = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_nonfinite, parse_float=_lossless_float)
        # 1e999 is JSON syntax but Python would otherwise quietly make Infinity.
        digest(schema)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise SafetyError('native-schema-invalid-bounded-json') from None
    if not isinstance(schema, list) or not schema or any(not isinstance(row, dict) for row in schema):
        raise SafetyError('native-schema-component-array-required')
    _validate_logical_properties(schema)
    if redact(schema) != schema:
        raise SafetyError('credentials-not-allowed-in-native-schema')
    return schema, hashlib.sha256(text.encode('utf-8')).hexdigest()


def inventory(schema):
    """Only documented structural locations become targets; future controls stay intact."""
    targets = []
    sku_count = 0
    def images(component, prefix, dimension, sku_index=None):
        values = component.get('value')
        if not isinstance(values, list):
            return
        for i, image in enumerate(values):
            if not isinstance(image, dict) or image.get('componentCode') not in ('img', 'detail'):
                continue
            props = image.get('properties')
            if not isinstance(props, list):
                continue
            found = [(j, prop) for j, prop in enumerate(props) if isinstance(prop, dict) and prop.get('key') == 'imgUrl']
            if len(found) > 1:
                raise SafetyError('ambiguous-native-schema-image-url-property')
            if not found or not isinstance(found[0][1].get('value'), str):
                continue
            keys = {}
            for prop in props:
                if not isinstance(prop, dict) or prop.get('key') not in ('colorId', 'imgRefId', 'orderSort', 'index'):
                    continue
                if prop['key'] in keys:
                    raise SafetyError('ambiguous-native-schema-image-reference-property')
                keys[prop['key']] = copy.deepcopy(prop.get('value'))
            j, prop = found[0]
            targets.append({'pointer':prefix + '/value/' + str(i) + '/properties/' + str(j) + '/value',
                            'componentCode':component['componentCode'], 'dimension':dimension,
                            'skuRowIndex':sku_index, 'imageIndex':i, 'oldValue':prop['value'],
                            'references':keys})
    for i, component in enumerate(schema):
        prefix = '/' + str(i)
        if component.get('componentCode') in PRODUCT_IMAGES:
            images(component, prefix, 'product')
        if component.get('componentCode') != 'SKUS' or not isinstance(component.get('value'), list):
            continue
        for j, row in enumerate(component['value']):
            if not isinstance(row, dict) or row.get('componentCode') != 'SKU' or not isinstance(row.get('value'), list):
                continue
            sku_count += 1
            for k, child in enumerate(row['value']):
                if isinstance(child, dict) and child.get('componentCode') in SKU_IMAGES:
                    images(child, prefix + '/value/' + str(j) + '/value/' + str(k), 'sku', sku_count - 1)
    return targets, sku_count


def _set_existing(schema, pointer, value):
    parts = pointer.split('/')[1:]
    current = schema
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    current[parts[-1]] = value


def _check_color_consistency(targets, replacements):
    groups = {}
    for target in targets:
        ref = target['references']
        if target['dimension'] != 'sku' or 'colorId' not in ref or 'imgRefId' not in ref:
            continue
        # Equality of retained reference strings is not proof of a real mappingId.
        group = digest([target['componentCode'], ref['colorId'], ref['imgRefId'],
                        ref.get('orderSort', target['imageIndex']), ref.get('index')])
        groups.setdefault(group, []).append(target)
    for members in groups.values():
        if not any(t['pointer'] in replacements for t in members):
            continue
        urls = {replacements.get(t['pointer'], t['oldValue']) for t in members}
        if len(urls) != 1:
            raise SafetyError('same-color-image-slots-must-remain-consistent-select-full-group')


class ProductSchemaService(ProductService):
    def _read(self, profile, url, params, *, skill='jdo-product-update'):
        shop = self.ops.shop(profile)
        response = super()._read(profile, url, params, skill=skill)
        if not _same_identity(self.client.identity(profile), shop):
            raise SafetyError('native-schema-shop-changed-during-read')
        return response

    def _template(self, profile, product_id, category):
        response = self._read(profile, SCHEMAS, {'lastCategoryId':category, 'scene':'pop', 'productId':int(product_id)}, skill='jdo-product-publish')
        schema, text_hash = parse_schema(response)
        return schema, text_hash, digest(response)

    def capture_edit(self, profile, product_id):
        product_id = identifier(product_id)
        shop = self.ops.shop(profile)
        before = self.detail(profile, product_id)
        category, _ = _category(before)
        _, rows = _sku_source(before)
        sku_ids = []
        for row in rows:
            if not isinstance(row, dict) or (row.get('productId') is not None and identifier(row['productId']) != product_id):
                raise SafetyError('native-edit-sku-parent-mismatch')
            sku_ids.append(identifier(row.get('skuId')))
        if not sku_ids or len(set(sku_ids)) != len(sku_ids):
            raise SafetyError('native-edit-complete-unique-sku-detail-required')
        census = self.list_skus(profile, product_id, page_size=50)
        observed = [identifier(row.get('skuId')) for row in census['items']]
        if not census['complete'] or census['reportedTotal'] is None or set(observed) != set(sku_ids):
            raise SafetyError('native-edit-complete-sku-census-required')
        schema, text_hash, response_hash = self._template(profile, product_id, category)
        inventory(schema)
        after = self.detail(profile, product_id)
        if digest(after) != digest(before):
            raise SafetyError('native-edit-source-changed-during-capture')
        if not _same_identity(self.client.identity(profile), shop):
            raise SafetyError('native-edit-shop-changed-during-capture')
        _validate_logical_properties(before)
        if redact(before) != before:
            raise SafetyError('private-native-product-detail-capture-refused')
        scope = {'shop':{k:shop[k] for k in ('profile','shopName','shopId','venderId')},
                 'runtimeVersion':VERSION, 'productId':product_id, 'lastCategoryId':category,
                 'schema':schema, 'skuIds':sku_ids, 'productDetail':copy.deepcopy(before), 'productDetailHash':digest(before),
                 'schemaTextSha256':text_hash, 'schemaResponseHash':response_hash,
                 'skuPageHashes':census['sourcePageHashes'], 'observedAt':time.time()}
        record = {'captureId':uuid.uuid4().hex[:24], 'scope':scope, 'fingerprint':digest(scope)}
        atomic_json(self._path('captures',record['captureId']), record)
        return self._capture_view(record)

    def _path(self, kind, ident):
        if kind not in ('captures','drafts') or not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{24}',ident):
            raise SafetyError('native-schema-safe-record-id-required')
        return safe_join(self.state, 'product-schemas/' + kind + '/' + ident + '.json')

    def _load(self, kind, ident):
        record = read_json(self._path(kind, ident))
        if not isinstance(record, dict) or not isinstance(record.get('scope'), dict) or digest(record['scope']) != record.get('fingerprint'):
            raise SafetyError('native-schema-record-missing-or-modified')
        if record['scope'].get('runtimeVersion') != VERSION:
            raise SafetyError('native-schema-runtime-changed-capture-again')
        scope = record['scope']
        if ('rawSchema' in scope) != ('schemaCompiler' in scope):
            raise SafetyError('native-raw-schema-alias-requires-compilation-proof')
        if 'schemaCompiler' in scope:
            from .template_compile import verify_compiled_scope
            proof = scope['schemaCompiler']
            original_id = proof.get('originalCaptureId') if isinstance(proof, dict) else None
            if kind != 'captures' or original_id == ident:
                raise SafetyError('native-compiled-capture-origin-required')
            original = self._load('captures', original_id)
            if 'schemaCompiler' in original['scope'] or proof.get('originalCaptureFingerprint') != original['fingerprint']:
                raise SafetyError('native-compiled-capture-origin-changed')
            wanted = {**original['scope'], 'schema':scope['schema'],
                      'rawSchema':original['scope']['schema'], 'schemaCompiler':proof}
            if digest(scope) != digest(wanted):
                raise SafetyError('native-compiled-source-must-match-original-capture')
            verify_compiled_scope(scope)
        return record

    def compile_capture(self, capture_id):
        from .template_compile import compile_native, compilation_proof, verify_compiled_scope
        from .state import FileLock
        original = self._load('captures', capture_id)
        if 'schemaCompiler' in original['scope']:
            result = verify_compiled_scope(original['scope'])
            return {**self._capture_view(original), 'bindings':result['bindings'],
                    'saleSources':result['saleSources'], 'automaticBindingsPrepared':True}
        source = original['scope']
        result = compile_native(source['schema'], source['productDetail'])
        proof = compilation_proof(source['schema'], source['productDetail'], result,
                                  capture_id, original['fingerprint'])
        scope = {**copy.deepcopy(source), 'rawSchema':copy.deepcopy(source['schema']),
                 'schema':result['schema'], 'schemaCompiler':proof}
        ident = digest({'capture':original['fingerprint'], 'proof':proof})[:24]
        record = {'captureId':ident, 'scope':scope, 'fingerprint':digest(scope)}
        with FileLock(self.state / 'native-compile.lock'):
            path = self._path('captures', ident)
            if path.exists():
                current = self._load('captures', ident)
                if current['fingerprint'] != record['fingerprint']:
                    raise SafetyError('native-compiled-capture-conflict')
                record = current
            else:
                atomic_json(path, record)
        return {**self._capture_view(record), 'bindings':result['bindings'],
                'saleSources':result['saleSources'], 'automaticBindingsPrepared':True}

    @staticmethod
    def _capture_view(record):
        targets, count = inventory(record['scope']['schema'])
        return {**copy.deepcopy(record), 'imageTargets':targets, 'schemaSkuRowCount':count,
                'submissionReady':False, 'skuIdentityMappingVerified':False,
                'source':'official-edit-template-with-repeated-detail-and-sku-census-evidence',
                'notice':'Template is not proof of populated values or UUID-to-SKU mapping; no product write is prepared.'}

    def capture(self, capture_id):
        return self._capture_view(self._load('captures', capture_id))

    def draft_images(self, capture_id, changes):
        record = self._load('captures', capture_id)
        scope = record['scope']; profile = scope['shop']['profile']
        targets, count = inventory(scope['schema']); allowed = {t['pointer']:t for t in targets}
        if not isinstance(changes, list) or not changes or len(changes) > 1000:
            raise SafetyError('explicit-locally-bounded-image-slot-changes-required')
        seen = set()
        for change in changes:
            if not isinstance(change, dict) or set(change) != {'pointer','assetTaskId'} or not isinstance(change['assetTaskId'], str) or not re.fullmatch('[a-f0-9]{24}',change['assetTaskId']) or not isinstance(change['pointer'], str) or change['pointer'] not in allowed or change['pointer'] in seen:
                raise SafetyError('exact-existing-distinct-native-image-pointers-required')
            seen.add(change['pointer'])
        if count != len(scope['skuIds']):
            raise SafetyError('native-schema-sku-row-count-incomplete-cannot-draft-full-edit')
        if not _same_identity(self.ops.shop(profile), {**scope['shop'], 'shopType':'POP'}) or not _same_identity(self.client.identity(profile), scope['shop']):
            raise SafetyError('native-schema-capture-shop-mismatch')
        current = self.detail(profile, scope['productId'])
        schema_now, _, _ = self._template(profile, scope['productId'], scope['lastCategoryId'])
        if digest(current) != scope['productDetailHash'] or digest(schema_now) != digest(scope['schema']):
            raise SafetyError('native-schema-source-stale-capture-again')
        materials = MaterialService(self.state, self.client); assets = {}; replacements = {}; preview = []
        for change in changes:
            task_id = change['assetTaskId']
            if task_id not in assets:
                task = self.ops.task(task_id)
                if task['scope']['shop'] != scope['shop'] or 'materialUpload' not in task['scope'] or task['status'] not in ('submitted','verified'):
                    raise SafetyError('same-profile-known-original-image-upload-required')
                status = materials.upload_status(task_id, refresh=True)
                if not status['storageVerified']:
                    raise SafetyError('fresh-original-image-storage-readback-required')
                assets[task_id] = status
            asset = assets[task_id]
            url = asset['asset']['imgUrl']; replacements[change['pointer']] = url
            preview.append({**change, 'oldValue':allowed[change['pointer']]['oldValue'], 'newValue':url,
                            'assetReceiptHash':asset['task']['resultReceiptSha256'],
                            'originalSha256':asset['originalSha256']})
        # Resolve known uploads by their original receipt before the same-shop gate.
        self.ops._assert_resolved(scope['shop'])
        _check_color_consistency(targets, replacements)
        updated = copy.deepcopy(scope['schema'])
        for pointer, value in replacements.items():
            _set_existing(updated, pointer, value)
        final_detail = self.detail(profile, scope['productId'])
        final_schema, _, _ = self._template(profile, scope['productId'], scope['lastCategoryId'])
        if digest(final_detail) != scope['productDetailHash'] or digest(final_schema) != digest(scope['schema']):
            raise SafetyError('native-schema-source-stale-capture-again')
        if not _same_identity(self.client.identity(profile), scope['shop']):
            raise SafetyError('native-schema-shop-changed-during-draft')
        draft_scope = {'captureId':capture_id, 'captureFingerprint':record['fingerprint'],
                       'shop':scope['shop'], 'productId':scope['productId'], 'lastCategoryId':scope['lastCategoryId'],
                       'runtimeVersion':VERSION, 'schema':updated, 'changes':preview, 'createdAt':time.time()}
        draft = {'draftId':uuid.uuid4().hex[:24], 'scope':draft_scope, 'fingerprint':digest(draft_scope)}
        atomic_json(self._path('drafts',draft['draftId']), draft)
        return self._draft_view(draft)

    @staticmethod
    def _draft_view(record):
        return {**copy.deepcopy(record), 'schema':copy.deepcopy(record['scope']['schema']),
                'changes':copy.deepcopy(record['scope']['changes']), 'submissionReady':False,
                'skuIdentityMappingVerified':False, 'productBound':False, 'remotePixelsVerified':False,
                'phase':'local-lossless-image-draft-not-submitted',
                'remaining':['live-schema-sku-identity-and-filled-values-contract',
                             'approved-schema-validation-and-full-edit-submission',
                             'receipt-bound-pending-and-online-image-verification']}

    def draft(self, draft_id):
        return self._draft_view(self._load('drafts', draft_id))
