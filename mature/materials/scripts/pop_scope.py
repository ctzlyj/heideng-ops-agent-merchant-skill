"""Exact parent SKU x slot accounting and evidence-based reuse helpers (offline).

This is a ledger/projection, not a business planning engine. It never queries or writes shops.
Legacy success counts and SPU membership cannot supply missing per-SKU evidence.
"""
from __future__ import annotations
from collections import Counter
import copy
from dataclasses import replace
import json
from pathlib import Path
import re
from pop_safety import atomic_json, fingerprint

IMAGE_SLOTS = ('white','transparent','scene1','scene2','selling')
STATUSES = ('unprocessed','blocked-reference','blocked-evidence','generated','submitted','accepted',
            'pending','approved','rejected','review-required','quality-failed','model-unavailable','rate-limited','unknown')
PROTECTED = {'approved','pending','accepted','submitted','unknown'}


def job_slots(job, agent):
    slots = list(agent._model_kinds(job))
    if job.needs_transparent:
        slots.append('transparent')
    if job.needs_selling_points:
        slots.extend(('point1','point2','point3'))
    return slots


def make_scope(prepared, *, agent, snapshot=None, target_slots=None):
    cells = []
    seen = set()
    for job in prepared.jobs:
        if not job.sku_ids or len(set(job.sku_ids)) != len(job.sku_ids):
            raise ValueError('Parent has empty or duplicate SKU scope')
        if set(job.sku_ids) != {sku for sku, _ in job.skus}:
            raise ValueError('Parent sku_ids differs from frozen SKU source rows; never infer missing siblings')
        for sku in job.sku_ids:
            if sku in seen:
                raise ValueError('Parent SKU appears in multiple SPUs')
            seen.add(sku)
            for slot in job_slots(job, agent):
                cells.append({'spuId':job.spu_id,'skuId':sku,'slot':slot})
            if sku in job.short_title_sku_ids:
                cells.append({'spuId':job.spu_id,'skuId':sku,'slot':'shortTitle'})
    if target_slots is not None:
        if set(target_slots) != seen:
            raise ValueError('Exact needed-slot map must account for every frozen parent SKU')
        allowed = {(c['skuId'], c['slot']) for c in cells}
        if any(len(set(slots)) != len(slots) or any((sku,slot) not in allowed for slot in slots) for sku,slots in target_slots.items()):
            raise ValueError('Exact needed-slot map extends parent needs or contains duplicate slots')
        cells = [c for c in cells if c['slot'] in target_slots[c['skuId']]]
    value = {'formatVersion':1, 'taskSignature':agent._task_signature(prepared),
             'targetSkuIds':sorted(seen), 'cells':cells, 'snapshot':copy.deepcopy(snapshot or {}),
             'slotBasis':'frozen-job-needs; legacy flags are conservative, not per-SKU audit evidence'}
    value['scopeHash'] = fingerprint(value)
    return value


def verify_scope(scope):
    if not isinstance(scope, dict) or scope.get('formatVersion') != 1 or scope.get('scopeHash') != fingerprint(
            {k:v for k,v in scope.items() if k != 'scopeHash'}):
        raise ValueError('Frozen parent scope changed')
    return scope


def cell_key(cell):
    return '/'.join((str(cell['spuId']),str(cell['skuId']),str(cell['slot'])))


class ScopeLedger:
    def __init__(self, path, scope):
        self.path = Path(path) if path is not None else None
        self.scope = copy.deepcopy(verify_scope(scope))
        if self.path and self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if self.data.get('scope') != self.scope:
                raise ValueError('Parent scope or inventory snapshot changed; do not replace task denominator')
        else:
            self.data = {'scope':self.scope,'cells':{cell_key(c):{'status':'unprocessed'} for c in scope['cells']}}
            self.save()
        if set(self.data['cells']) != {cell_key(c) for c in self.scope['cells']}:
            raise ValueError('Coverage cells differ from frozen parent scope')

    def save(self):
        if self.path:
            atomic_json(self.path,self.data)

    def report(self):
        counts = Counter(v['status'] for v in self.data['cells'].values())
        return {'scopeHash':self.scope['scopeHash'],'snapshot':self.scope['snapshot'],
                'targetSkuCount':len(self.scope['targetSkuIds']),'targetSlotCount':len(self.data['cells']),
                'counts':{s:counts[s] for s in STATUSES},
                'remainingSlotCount':len(self.data['cells']) - counts['approved'],
                'allApproved':bool(self.data['cells']) and counts['approved'] == len(self.data['cells']),
                'cells':copy.deepcopy(self.data['cells']), 'warnings':[]}

    def record_binding(self, request, status):
        if status not in {'submitted','accepted','unknown','rejected'}:
            raise ValueError('Only explicit submission outcomes; audit success needs per-SKU readback')
        body = request.get('body',{})
        if request.get('fingerprint') != fingerprint(body):
            raise ValueError('Binding fingerprint differs from original request')
        rows = body.get('skuMaterials',[])
        if [str(row['skuId']) for row in rows] != request.get('skuIds'):
            raise ValueError('Binding scope does not match exact payload rows')
        keys = []
        types = {(31,1):'white',(32,1):'scene1',(32,2):'scene2',(33,1):'selling',
                 (36,1):'transparent',(1002,1):'point1',(1002,2):'point2',(1002,3):'point3'}
        for row in rows:
            if str(row['productId']) != str(request['spuId']):
                raise ValueError('Binding SPU differs from frozen request')
            for m in row.get('materials',[]):
                if int(m['materialType']) != int(request['materialType']) or (m.get('skuId') is not None and str(m['skuId']) != str(row['skuId'])):
                    raise ValueError('Binding material type/SKU differs from its original request row')
                slot = types.get((int(m['materialType']),int(m['order'])))
                key = cell_key({'spuId':row['productId'],'skuId':row['skuId'],'slot':slot})
                if key not in self.data['cells'] or key in keys:
                    raise ValueError('Binding outside parent scope or duplicate cell')
                previous = self.data['cells'][key]
                if previous['status'] in PROTECTED and not (
                        previous['status'] == status and previous.get('requestFingerprint') == request['fingerprint']):
                    raise ValueError('Protected/unknown original slot; reconcile, do not overwrite')
                keys.append(key)
        originals = self.data.setdefault('bindingRequests', {})
        previous_request = originals.get(request['fingerprint'])
        if previous_request is not None and any(previous_request.get(field) != request.get(field) for field in ('spuId','materialType','skuIds','body','preservedMaterialsBySku')):
            raise ValueError('Original binding association changed; preserve its exact request')
        originals.setdefault(request['fingerprint'], copy.deepcopy(request))
        for key in keys:
            self.data['cells'][key] = {**self.data['cells'][key], 'status':status, 'phase':'binding', 'requestFingerprint':request['fingerprint']}
        self.save()

    def record_readback(self, snapshot):
        # This method consumes supplied interface data only. It never expands the query scope.
        from jd_material_agent import _evaluate_binding_request
        types = {(31,1):'white',(32,1):'scene1',(32,2):'scene2',(33,1):'selling',
                 (36,1):'transparent',(1002,1):'point1',(1002,2):'point2',(1002,3):'point3'}
        parent_spus = {c['skuId']:c['spuId'] for c in self.scope['cells']}
        normalized = {}
        observations = {}
        for sku, materials in snapshot.items():
            sku = str(sku)
            normalized[sku] = []
            for m in materials:
                if m.get('skuId') is not None and str(m['skuId']) != sku:
                    raise ValueError('Readback SKU does not match requested exact SKU')
                if m.get('productId') is not None and str(m['productId']) != parent_spus.get(sku):
                    continue  # Wrong product association cannot certify this parent's request.
                normalized[sku].append(m)
                slot = types.get((int(m.get('materialType',0)),int(m.get('order',0))))
                key = cell_key({'spuId':parent_spus.get(sku),'skuId':sku,'slot':slot})
                if key not in self.data['cells']:
                    continue
                if key in observations:
                    raise ValueError('Duplicate per-SKU audit readback slot')
                observations[key] = (sku, m)

        verified = {}
        updates = {}
        for key, (sku, material) in observations.items():
            previous = self.data['cells'][key]
            digest = previous.get('requestFingerprint')
            if digest:
                request = (self.data.get('bindingRequests') or {}).get(digest)
                try:
                    targets = [m for row in request['body']['skuMaterials'] if str(row['skuId']) == sku
                               for m in row['materials'] if int(m['materialType']) == int(material['materialType']) and int(m['order']) == int(material['order'])]
                    if len(targets) != 1 or int(request['materialType']) != int(material['materialType']) or (targets[0].get('skuId') is not None and str(targets[0]['skuId']) != sku):
                        continue
                except (KeyError, TypeError, ValueError):
                    continue  # Missing or unrelated original target is not recovered inventory proof.
                unit = (digest, sku)
                if unit not in verified:
                    request = (self.data.get('bindingRequests') or {}).get(digest)
                    matches = False
                    if isinstance(request, dict) and request.get('fingerprint') == digest and fingerprint(request.get('body',{})) == digest:
                        rows = [r for r in request['body'].get('skuMaterials',[]) if str(r.get('skuId')) == sku]
                        if len(rows) == 1 and str(request.get('spuId')) == parent_spus.get(sku) and str(rows[0].get('productId')) == parent_spus.get(sku) and sku in request.get('skuIds',[]):
                            # Reuse the mature matcher on this exact SKU/type family, including preserved
                            # original orders. Other SKUs may be absent, but remain unresolved in the parent.
                            exact = {**request, 'skuIds':[sku], 'body':{'skuMaterials':[rows[0]]}}
                            if request.get('preservedMaterialsBySku') is not None:
                                preserved = request['preservedMaterialsBySku']
                                if sku in preserved:
                                    exact['preservedMaterialsBySku'] = {sku:preserved[sku]}
                            try:
                                originals = rows[0]['materials'] + (exact.get('preservedMaterialsBySku') or {}).get(sku, [])
                                original_shape, _ = _evaluate_binding_request(exact, {sku:originals})
                                if original_shape != 'mismatch':
                                    outcome, _ = _evaluate_binding_request(exact, {sku:normalized[sku]})
                                    matches = outcome in {'approved','pending','failed'}
                            except (KeyError, TypeError, ValueError):
                                matches = False
                    verified[unit] = matches
                if not verified[unit]:
                    continue  # Old/missing/wrong content or unavailable original request: keep the hold.
            elif previous['status'] in {'intent','unknown','accepted','submitted'}:
                continue  # A legacy/generation hold without its original target cannot be certified by inventory.
            status = {4:'approved',3:'pending',5:'rejected'}.get(int(material.get('status',0)))
            if status is None:
                continue
            updates[key] = {**previous, 'status':status, 'readbackSha256':fingerprint(material)}
        self.data['cells'].update(updates)
        self.save()

    def record_generated(self, group, slot, artifact, *, agent, quality_review):
        if not quality_review or quality_review.get('accepted') is not True or not quality_review.get('reason'):
            raise ValueError('Generated image needs explicit local visual/identity review before reusable status')
        if group.get('status') != 'ready' or slot not in group['slots'] or not Path(artifact).is_file():
            raise ValueError('Generated artifact lacks frozen group scope')
        if agent._file_sha256(Path(group['referencePath'])) != group['referenceSha256']:
            raise ValueError('Original reference bytes changed')
        digest = agent._file_sha256(Path(artifact))
        for sku in group['skuIds']:
            key = cell_key({'spuId':group['spuId'],'skuId':sku,'slot':slot})
            if self.data['cells'][key]['status'] in PROTECTED:
                continue
            self.data['cells'][key] = {'status':'generated','groupId':group['groupId'],
                'sourceSha256':group['referenceSha256'],'outputSha256':digest,
                'applicabilitySha256':fingerprint(group['review']), 'qualityReviewSha256':fingerprint(quality_review)}
        self.save()

    def record_group_hold(self, group, slot, status):
        if status not in set(STATUSES) - {'approved','pending','generated','unprocessed'}:
            if status != 'unknown':
                raise ValueError('Invalid generation hold outcome')
        for sku in group['skuIds']:
            key = cell_key({'spuId':group['spuId'],'skuId':sku,'slot':slot})
            if self.data['cells'][key]['status'] not in PROTECTED:
                self.data['cells'][key] = {**self.data['cells'][key], 'status':status,'phase':'generation','groupId':group['groupId']}
        self.save()


def validate_groups(scope, definitions, *, agent):
    verify_scope(scope)
    target = {cell_key(c) for c in scope['cells']}
    occupied = set()
    group_ids = set()
    groups = []
    for raw in definitions:
        group = copy.deepcopy(raw)
        gid = group.get('groupId','')
        ids = group.get('skuIds',[])
        slots = group.get('slots',[])
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',gid) or gid in group_ids:
            raise ValueError('Invalid/duplicate groupId')
        if not ids or len(set(ids)) != len(ids) or not slots or len(set(slots)) != len(slots) or set(slots) - set(IMAGE_SLOTS):
            raise ValueError('Invalid group SKU or image slot scope')
        keys = {cell_key({'spuId':group.get('spuId'),'skuId':sku,'slot':slot}) for sku in ids for slot in slots}
        if not keys.issubset(target) or occupied.intersection(keys):
            raise ValueError('Group overlaps or extends frozen parent SKU x slot scope')
        group_ids.add(gid);occupied.update(keys)
        group['status'] = 'ready'
        source = Path(group.get('referencePath',''))
        try:
            if not source.is_file() or agent._file_sha256(source) != group.get('referenceSha256'):
                group['status'] = 'blocked-reference'
        except OSError:
            group['status'] = 'blocked-reference'
        review = group.get('review',{})
        if not all(isinstance(review.get(k),str) and review[k].strip() for k in ('appearance','components','quantity')):
            if group['status'] == 'ready':group['status'] = 'blocked-evidence'
        applicable = review.get('slotApplicability',{})
        sources = review.get('skuReferences',{})
        if set(sources) != set(ids) or any(not isinstance(applicable.get(k),str) or not applicable[k].strip() for k in slots):
            if group['status'] == 'ready':group['status'] = 'blocked-evidence'
        else:
            for entry in sources.values():
                try:
                    path = Path(entry['path'])
                    if not path.is_file() or agent._file_sha256(path) != entry.get('sha256'):
                        group['status'] = 'blocked-reference'
                except (KeyError,TypeError,OSError):
                    group['status'] = 'blocked-reference'
        groups.append(group)
    return groups


def group_prepared(parent, group, *, agent):
    original = next(j for j in parent.jobs if j.spu_id == group['spuId'])
    ids = tuple(group['skuIds'])
    skus = tuple((sku,title) for sku,title in original.skus if sku in ids)
    slots = group['slots']
    job = replace(original, representative_sku_id=ids[0], sku_ids=ids, skus=skus,
                  short_title_sku_ids=(), needs_selling_points=False, needs_white='white' in slots,
                  needs_transparent='transparent' in slots, needs_scenes=bool(set(slots)&{'scene1','scene2'}),
                  needs_selling_image='selling' in slots, image_kinds=tuple(k for k in slots if k != 'transparent'))
    rows = tuple(row for row in parent.rows if row.sku_id in ids)
    return replace(parent, rows=rows, jobs=(job,), filtered_rows=len(rows))


def legacy_report(scope, directories, *, agent):
    ledger = ScopeLedger(None,scope)
    warnings = set()
    for directory in directories:
        path = Path(directory)/'.state/task.json'
        if not path.is_file():continue
        state = json.loads(path.read_text(encoding='utf-8'))
        warnings.add('legacy-coverage-unverified')
        for item in (state.get('jobs') or {}).values():
            for record in (item.get('material_bindings') or {}).values():
                request = record.get('request')
                if not request:
                    continue  # Neither job sku_ids nor same-SPU ancestry proves a submission.
                chunks = record.get('chunks',[])
                if chunks:
                    # Only original explicit chunks, never the unsubmitted suffix of a parent request.
                    for chunk in chunks:
                        body = chunk.get('body',{})
                        exact = {**request,'body':body,'skuIds':[str(r['skuId']) for r in body.get('skuMaterials',[])],
                                 'fingerprint':fingerprint(body)}
                        status = 'accepted' if chunk.get('status') == 'accepted' else 'unknown'
                        ledger.record_binding(exact,status)
                elif record.get('status') in {'unknown','intent'}:
                    ledger.record_binding(request,'unknown')
                # Aggregate pending/approved counts without exact readback do not certify individual slots.
    result = ledger.report();result['warnings'] = sorted(warnings)
    return result
