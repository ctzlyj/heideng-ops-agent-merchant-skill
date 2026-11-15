"""Original-scope effects evidence, immutable observations and verified prefixes."""
import json, math, re, unicodedata
from pathlib import Path
from .operations import digest
from .safety import SafetyError, redact, safe_join, atomic_json
from .short_title_import_state import path, valid_time, HASH
from .video_delivery import _once

FOLDERS = ('short-title-effect-observations', 'short-title-effect-receipts')
HEAD = 'short-title-effect-heads'
MAX_OBSERVATIONS = 10000
MAX_BYTES = 64 * 1024 * 1024

def _error(): raise SafetyError('original-native-title-effect-evidence-required')
def _hash(value): return isinstance(value, str) and HASH.fullmatch(value) is not None

def _read(file):
    if not file.is_file() or not 0 < file.stat().st_size <= MAX_BYTES: _error()
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result: _error()
            result[key] = value
        return result
    try:
        return json.loads(file.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                          parse_constant=lambda value: _error())
    except (ValueError, OSError, RecursionError): _error()

def _files(state, folder, root):
    directory = path(state, folder, root['importId'], suffix='')
    if not directory.exists(): return {}
    if not directory.is_dir(): _error()
    result = {}
    for entry in directory.iterdir():
        file = safe_join(Path(state).absolute(), folder+'/'+root['importId']+'/'+entry.name)
        if not file.is_file() or not re.fullmatch(r'[0-9]{6}\.json', file.name) or not 1 <= int(file.stem) <= MAX_OBSERVATIONS or len(result) >= MAX_OBSERVATIONS: _error()
        result[int(file.stem)] = _read(file)
    return result

class _Context:
    def __init__(self, state, root, anchors):
        from .short_title_contract import source_context
        from .short_titles import ShortTitlePlans
        from .short_title_result_state import read_log
        self.state = Path(state).absolute(); self.root = root; self.anchors = anchors
        plan = ShortTitlePlans(state, None).plan(root['scope']['planId'])
        self.audit_fp = plan['scope']['auditFingerprint']
        _, self.original = source_context(state, plan['scope']['auditId'], self.audit_fp)
        self.products = {}
        for row in self.original: self.products.setdefault(row['productId'], []).append(row['skuId'])
        self.count = read_log(state, root, anchors)[1]
        self.sequence = 0; self.latest = {}; self.receipt_sha = root['fingerprint']
        owner = root['scope']['shop']
        self.identity_sha = digest({key: str(owner[key]) if key != 'shopType' else 'POP' for key in ('venderId','shopId','shopName','shopType')})

    def results(self, sequence, receipt_sha):
        from .short_title_result_state import result_rows
        if type(sequence) is not int or not self.sequence <= sequence <= self.count: _error()
        for number in range(self.sequence+1, sequence+1):
            item = _read(safe_join(self.state, f'short-title-result-observations/{self.root["importId"]}/{number:06d}.json'))
            self.latest[item['batch']] = item
            receipt = _read(safe_join(self.state, f'short-title-result-receipts/{self.root["importId"]}/{number:06d}.json'))
            self.receipt_sha = digest(receipt)
        self.sequence = sequence
        if receipt_sha != self.receipt_sha: _error()
        return {row['skuId']: row for row in result_rows(self.root, self.anchors, self.latest)}

    def check(self, value):
        keys = {'importId','fingerprint','originalAuditFingerprint','originalResultReceiptSha256','originalResultSequence','rows','identitySha256','originalAnchors','detailSources','healthSource','currentIdentityVerified','sourceDetailsStable','currentOriginalScopeComplete','currentTargetTitlesMatch','actualTitlesVerified','formalAuditVerified','portalVerified','healthVerified','C3ReceiptPersisted','imported','retryAuthorized'}
        root = self.root
        if not isinstance(value, dict) or set(value) != keys or redact(value) != value or value['importId'] != root['importId'] or value['fingerprint'] != root['fingerprint'] or value['originalAuditFingerprint'] != self.audit_fp or value['identitySha256'] != self.identity_sha or value['currentIdentityVerified'] is not True: _error()
        if any(value[key] is not False for key in ('formalAuditVerified','portalVerified','healthVerified','C3ReceiptPersisted','imported','retryAuthorized')): _error()
        anchors = value['originalAnchors']
        if not isinstance(anchors, dict): _error()
        for key, sha in anchors.items():
            if not isinstance(key,str) or not re.fullmatch(r'[0-9]{6}',key) or not 1 <= int(key) <= len(root['scope']['chunks']) or not _hash(sha) or (int(key),'create') not in self.anchors or sha != digest(self.anchors[int(key),'create']): _error()
        processed = self.results(value['originalResultSequence'], value['originalResultReceiptSha256'])
        details = value['detailSources']; rows = value['rows']; health = value['healthSource']
        pids = sorted(self.products,key=int)
        if not isinstance(details,list) or len(details) != len(pids) or not isinstance(rows,list) or len(rows) != len(self.original): _error()
        missing = set(); stable = full = True
        for pid, source in zip(pids, details):
            if not isinstance(source,dict) or set(source) != {'productId','startSha256','endSha256','missingOriginalSkuIds','additionalCurrentSkuIds'} or source['productId'] != pid or not all(_hash(source[key]) for key in ('startSha256','endSha256')): _error()
            absent = source['missingOriginalSkuIds']; extra = source['additionalCurrentSkuIds']; original = self.products[pid]
            if not isinstance(absent,list) or absent != [sku for sku in original if sku in absent] or not isinstance(extra,list) or len(extra) != len(set(extra)): _error()
            from .products import identifier
            if any(not isinstance(sku,str) or identifier(sku) != sku or sku in original for sku in extra) or extra != sorted(extra,key=int): _error()
            missing.update(absent); stable = stable and source['startSha256'] == source['endSha256']; full = full and not absent and not extra
        if value['sourceDetailsStable'] is not stable or value['currentOriginalScopeComplete'] is not full: _error()
        if not isinstance(health,dict) or set(health) != {'complete','sourcePageHashes','reportedTotal','originalValuesComplete'} or type(health['complete']) is not bool or type(health['originalValuesComplete']) is not bool or not isinstance(health['sourcePageHashes'],list) or len(health['sourcePageHashes']) > 1000 or any(not _hash(sha) for sha in health['sourcePageHashes']): _error()
        total = health['reportedTotal']
        if total is not None and (type(total) is not int or not 0 <= total <= 1000000) or health['complete'] and (total is None or not health['sourcePageHashes']): _error()
        target_rows = []; health_complete = health['complete']
        row_keys = {'productId','skuId','originalOnSale','target','actualShortTitle','actualFieldObserved','actualTitleMatchesProposed','actualTitleVerified','processingOutcome','proposedShortTitle','healthScore','healthTitleIssue','healthRowObserved','formalAuditStatus','formalAuditVerified','retryAuthorized'}
        for original, row in zip(self.original, rows):
            if not isinstance(row,dict) or set(row) != row_keys or row['skuId'] != original['skuId'] or row['productId'] != original['productId'] or row['originalOnSale'] is not original['onSale'] or row['formalAuditStatus'] != 'unverified-source-contract' or row['formalAuditVerified'] is not False or row['retryAuthorized'] is not False: _error()
            result = processed.get(row['skuId']); target = result is not None
            if row['target'] is not target or row['processingOutcome'] != (result['outcome'] if target else 'not-target') or row['proposedShortTitle'] != (result['proposedShortTitle'] if target else None): _error()
            if type(row['actualFieldObserved']) is not bool or type(row['healthRowObserved']) is not bool: _error()
            title = row['actualShortTitle']
            if row['actualFieldObserved']:
                if row['skuId'] in missing or not isinstance(title,str) or len(title) > 4096 or any(unicodedata.category(c).startswith('C') for c in title): _error()
            elif title is not None: _error()
            match = bool(target and row['actualFieldObserved'] and stable and title == result['proposedShortTitle'])
            verified = match and result['outcome'] == 'success' and full
            if row['actualTitleMatchesProposed'] is not match or row['actualTitleVerified'] is not verified: _error()
            score = row['healthScore']; issue = row['healthTitleIssue']
            if score is not None and (type(score) not in (int,float) or not math.isfinite(score) or not 0 <= score <= 100) or issue is not None and type(issue) is not bool or row['healthRowObserved'] and not health['complete']: _error()
            health_complete = health_complete and score is not None and issue is not None and row['healthRowObserved']
            if target: target_rows.append(row)
        if health['originalValuesComplete'] is not bool(health_complete) or value['currentTargetTitlesMatch'] is not (bool(target_rows) and all(row['actualTitleMatchesProposed'] for row in target_rows)) or value['actualTitlesVerified'] is not (bool(target_rows) and all(row['actualTitleVerified'] for row in target_rows)): _error()

def read_log(state, root, anchors, *, repair=False):
    observations = _files(state,FOLDERS[0],root); receipts = _files(state,FOLDERS[1],root)
    head_path = path(state,HEAD,root['importId']); exists = head_path.exists(); head = _read(head_path) if exists else None
    head_keys = {'importId','fingerprint','sequence','receiptSha256'}
    if exists and (not isinstance(head,dict) or set(head) != head_keys or head['importId'] != root['importId'] or head['fingerprint'] != root['fingerprint'] or type(head['sequence']) is not int or not 1 <= head['sequence'] <= MAX_OBSERVATIONS or not _hash(head['receiptSha256'])): _error()
    count = len(observations)
    if set(observations) != set(range(1,count+1)) or set(receipts)-set(observations): _error()
    if not count:
        if exists or receipts: _error()
        return None,0,root['fingerprint']
    context = _Context(state,root,anchors); previous = root['fingerprint']; hashes = {0:previous}; missing = []
    for sequence in range(1,count+1):
        item = observations[sequence]
        if not isinstance(item,dict) or set(item) != {'importId','fingerprint','sequence','previousReceiptSha256','observedAt','observation'} or redact(item) != item or item['importId'] != root['importId'] or item['fingerprint'] != root['fingerprint'] or type(item['sequence']) is not int or item['sequence'] != sequence or item['previousReceiptSha256'] != previous or not valid_time(item['observedAt']): _error()
        context.check(item['observation'])
        receipt = {'importId':root['importId'],'fingerprint':root['fingerprint'],'sequence':sequence,'observationSha256':digest(item),'previousReceiptSha256':previous}
        if sequence not in receipts: missing.append((sequence,receipt))
        elif not isinstance(receipts[sequence],dict) or set(receipts[sequence]) != set(receipt) or type(receipts[sequence]['sequence']) is not int or receipts[sequence] != receipt: _error()
        previous = digest(receipt); hashes[sequence] = previous
    expected = {'importId':root['importId'],'fingerprint':root['fingerprint'],'sequence':count,'receiptSha256':previous}
    if head != expected:
        if not repair: _error()
        if not exists:
            if count != 1: _error()
        elif head['sequence'] != count-1 or head['receiptSha256'] != hashes[count-1]: _error()
    if missing and not repair: _error()
    if repair:
        for sequence, receipt in missing: _once(path(state,FOLDERS[1],root['importId'],suffix=f'/{sequence:06d}.json'),receipt)
        if head != expected: atomic_json(head_path,expected)
    return observations[count],count,previous

def append_observation(state, root, anchors, value, observed_at):
    latest, count, previous = read_log(state,root,anchors)
    if count >= MAX_OBSERVATIONS or not valid_time(observed_at): _error()
    context = _Context(state,root,anchors); context.check(value)
    if latest is not None:
        old = latest['observation']
        if value['originalResultSequence'] < old['originalResultSequence'] or any(value['originalAnchors'].get(key) != sha for key,sha in old['originalAnchors'].items()): _error()
    sequence = count+1
    item = {'importId':root['importId'],'fingerprint':root['fingerprint'],'sequence':sequence,'previousReceiptSha256':previous,'observedAt':observed_at,'observation':value}
    if len(json.dumps(item,ensure_ascii=False,allow_nan=False).encode('utf-8')) > MAX_BYTES: raise SafetyError('original-effect-evidence-local-size-budget-exceeded-no-truncation')
    receipt = {'importId':root['importId'],'fingerprint':root['fingerprint'],'sequence':sequence,'observationSha256':digest(item),'previousReceiptSha256':previous}
    for folder, content in zip(FOLDERS,(item,receipt)): _once(path(state,folder,root['importId'],suffix=f'/{sequence:06d}.json'),content)
    atomic_json(path(state,HEAD,root['importId']),{'importId':root['importId'],'fingerprint':root['fingerprint'],'sequence':sequence,'receiptSha256':digest(receipt)})
    return sequence

def summary(latest,count):
    result = {'effectObservationCount':count,'effectEvidenceHistorical':True,'currentEffectSourceVerified':False,'formalAuditVerified':False,'portalVerified':False,'retryAuthorized':False}
    if latest is not None:
        result.update(actualTitlesVerified=latest['observation']['actualTitlesVerified'],effectObservedOriginalSkuCount=len(latest['observation']['rows']),effectObservedAt=latest['observedAt'])
    return result


def effect_rows(state,root,latest):
    if latest is not None:
        return [{**row,'effectObservedAt':latest['observedAt'],'effectObservationSequence':latest['sequence'],'effectEvidenceHistorical':True} for row in latest['observation']['rows']]
    from .short_titles import ShortTitlePlans
    from .short_title_contract import source_context
    plan=ShortTitlePlans(state,None).plan(root['scope']['planId'])
    _,original=source_context(state,plan['scope']['auditId'],plan['scope']['auditFingerprint'])
    return [{'productId':row['productId'],'skuId':row['skuId'],'originalOnSale':row['onSale'],'actualShortTitle':None,'actualFieldObserved':False,'actualTitleVerified':False,'effectObservedAt':None,'effectObservationSequence':None,'effectEvidenceHistorical':True,'formalAuditVerified':False,'retryAuthorized':False} for row in original]
