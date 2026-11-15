"""Original SKU health evidence. This is neither formal moderation nor portal proof."""
import math
import unicodedata
from .operations import digest
from .products import identifier
from .safety import SafetyError, redact

DETAIL_URL = '/rest/sp-product/v0/health-infos/{healthInfoId}'
MAX_ISSUES = 10000


class UnsafeHealthSource(SafetyError):
    pass


def _check_raw_privacy(data):
    # Only the documented asset sourceData URL is exempted from raw redaction.
    # Credential-bearing fields elsewhere still quarantine the whole observation.
    import copy,urllib.parse
    safe=copy.deepcopy(data)
    if isinstance(safe,dict) and isinstance(safe.get('improvementList'),list):
        for issue in safe['improvementList']:
            detail=issue.get('improvementDetail') if isinstance(issue,dict) else None
            if not isinstance(detail,dict) or not isinstance(detail.get('sourceData'),str):continue
            value=detail['sourceData']
            try:
                url=urllib.parse.urlsplit(value)
                if url.username is not None or url.password is not None:raise UnsafeHealthSource('credential-url-userinfo-native-health-source-refused')
                allowed=0<len(value)<=16384 and url.scheme in ('http','https') and bool(url.hostname) and url.username is None and url.password is None and not any(unicodedata.category(c).startswith('C') for c in value)
            except ValueError:allowed=False
            if allowed:detail['sourceData']=''
    if redact(safe)!=safe:raise UnsafeHealthSource('credential-bearing-native-health-source-refused')


def _refuse():
    raise SafetyError('original-native-health-source-required')


def project_detail(data, product_id, sku_id):
    _check_raw_privacy(data)
    product_id, sku_id = identifier(product_id), identifier(sku_id)
    if not isinstance(data, dict) or identifier(data.get('skuId')) != sku_id or identifier(data.get('productId')) != product_id:
        _refuse()
    echoed = identifier(data['healthScoreId']) if 'healthScoreId' in data else None
    if echoed is not None and echoed != sku_id:
        _refuse()
    try:
        sha = digest(data)
    except (ValueError, TypeError, RecursionError):
        _refuse()
    score = data.get('healthScore')
    score_observed = type(score) is int and 1 <= score <= 100
    issues = data.get('improvementList')
    issues_observed = isinstance(issues, list) and len(issues) <= MAX_ISSUES
    codes = []
    if issues_observed:
        for issue in issues:
            detail = issue.get('improvementDetail') if isinstance(issue, dict) else None
            code = detail.get('troubleCode') if isinstance(detail, dict) else None
            if not isinstance(code, str) or not 0 < len(code) <= 128 or any(unicodedata.category(c).startswith('C') for c in code) or redact(code) != code or '://' in code:
                issues_observed = False
                break
            codes.append(code)
    # sourceData may be a signed URL. It is hashed in memory, never returned or fetched.
    output = {'productId': product_id, 'skuId': sku_id, 'healthScoreId': echoed,
              'scoreObserved': score_observed, 'healthScore': score if score_observed else None,
              'issuesObserved': issues_observed, 'troubleCodes': sorted(codes) if issues_observed else None,
              'healthTitleIssue': 'hasShortTitle' in codes if issues_observed else None,
              'detailSha256': sha,
              'reason': 'native-health-detail-observed' if score_observed and issues_observed else 'native-health-detail-fields-unobserved'}
    if redact(output) != output:
        _refuse()
    return output


DETAIL_KEYS = {'productId','skuId','healthScoreId','scoreObserved','healthScore','issuesObserved','troubleCodes','healthTitleIssue','detailSha256','reason'}
LIST_KEYS = {'complete','paginationComplete','schemaObserved','reportedTotal','sourcePageHashes','rawRowCount','facts','legacyFacts'}
EVIDENCE_KEYS = {'version','detailRoute','listRoute','listBefore','listAfter','detailsBefore','detailsAfter'}
MAX_SKUS = 1000000


def unavailable_detail(product_id, sku_id):
    return {'productId':identifier(product_id),'skuId':identifier(sku_id),'healthScoreId':None,
            'scoreObserved':False,'healthScore':None,'issuesObserved':False,'troubleCodes':None,
            'healthTitleIssue':None,'detailSha256':None,'reason':'native-health-detail-unavailable'}


def project_list(source):
    if not isinstance(source,dict):
        _refuse()
    items=source.get('items');total=source.get('reportedTotal');hashes=source.get('sourcePageHashes')
    if not isinstance(items,list) or len(items)>MAX_SKUS:
        _refuse()
    total=total if type(total) is int and 0<=total<=MAX_SKUS else None
    hashes=hashes if isinstance(hashes,list) and len(hashes)<=1000 and all(_hash(v) for v in hashes) else []
    legacy=[project_legacy_fact(row) for row in items]
    if len({v['skuId'] for v in legacy})!=len(legacy):_refuse()
    facts=[];seen=set();schema=True
    for row in items:
        try:
            if not isinstance(row,dict):_refuse()
            sku=identifier(row.get('skuId'));pid=identifier(row.get('productId'))
            if sku in seen:_refuse()
            seen.add(sku);facts.append(project_detail(row,pid,sku))
        except (SafetyError,ValueError,TypeError):
            schema=False;facts=[];break
    paginated=source.get('complete') is True
    return {'complete':bool(paginated and schema and total==len(items) and hashes),
            'paginationComplete':paginated,'schemaObserved':schema,'reportedTotal':total,
            'sourcePageHashes':hashes,'rawRowCount':len(items),'facts':facts,'legacyFacts':legacy}


def _hash(value):
    import re
    return isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) is not None


def check_detail(value, product_id=None, sku_id=None):
    if not isinstance(value,dict) or set(value)!=DETAIL_KEYS or redact(value)!=value:_refuse()
    pid=identifier(value['productId']);sku=identifier(value['skuId'])
    if pid!=value['productId'] or sku!=value['skuId'] or product_id is not None and pid!=product_id or sku_id is not None and sku!=sku_id:_refuse()
    hid=value['healthScoreId']
    if hid is not None and (not isinstance(hid,str) or identifier(hid)!=sku):_refuse()
    score=value['healthScore'];observed=value['scoreObserved']
    if type(observed) is not bool or (observed and (type(score) is not int or not 1<=score<=100)) or (not observed and score is not None):_refuse()
    issues=value['issuesObserved'];codes=value['troubleCodes']
    if type(issues) is not bool:_refuse()
    if issues:
        if not isinstance(codes,list) or len(codes)>MAX_ISSUES or any(not isinstance(c,str) or not 0<len(c)<=128 or any(unicodedata.category(ch).startswith('C') for ch in c) or redact(c)!=c or '://' in c for c in codes) or codes!=sorted(codes):_refuse()
        if value['healthTitleIssue'] is not ('hasShortTitle' in codes):_refuse()
    elif codes is not None or value['healthTitleIssue'] is not None:_refuse()
    sha=value['detailSha256'];reason=value['reason']
    if sha is None:
        if value!=unavailable_detail(pid,sku):_refuse()
    elif not _hash(sha) or reason!=('native-health-detail-observed' if observed and issues else 'native-health-detail-fields-unobserved'):_refuse()
    return value


def check_list(value):
    if not isinstance(value,dict) or set(value)!=LIST_KEYS or redact(value)!=value:_refuse()
    if any(type(value[k]) is not bool for k in ('complete','paginationComplete','schemaObserved')):_refuse()
    total=value['reportedTotal'];count=value['rawRowCount'];hashes=value['sourcePageHashes'];facts=value['facts']
    if total is not None and (type(total) is not int or not 0<=total<=MAX_SKUS) or type(count) is not int or not 0<=count<=MAX_SKUS:_refuse()
    if not isinstance(hashes,list) or len(hashes)>1000 or any(not _hash(v) for v in hashes) or not isinstance(facts,list):_refuse()
    if len(facts)!=(count if value['schemaObserved'] else 0):_refuse()
    seen=set()
    for item in facts:
        check_detail(item)
        if not _hash(item['detailSha256']):_refuse()
        if item['skuId'] in seen:_refuse()
        seen.add(item['skuId'])
    expected=bool(value['paginationComplete'] and value['schemaObserved'] and total==count and hashes)
    if value['complete'] is not expected:_refuse()
    legacy=value['legacyFacts']
    if not isinstance(legacy,list) or len(legacy)!=count or len({v.get('skuId') for v in legacy if isinstance(v,dict)})!=count:_refuse()
    for fact in legacy:check_legacy_fact(fact)
    if value['schemaObserved']:
        for fact,detail in zip(legacy,facts):
            observed=type(fact['healthScore']) is int and 1<=fact['healthScore']<=100
            if fact['skuId']!=detail['skuId'] or fact['productId']!=detail['productId'] or not fact['productIdObserved'] or fact['sourceSha256']!=detail['detailSha256'] or detail['scoreObserved'] is not observed or detail['healthScore']!=(fact['healthScore'] if observed else None) or detail['healthTitleIssue'] is not fact['healthTitleIssue']:_refuse()
    return value


def _facts(detail):
    return {key:value for key,value in detail.items() if key!='detailSha256'}


def evaluate_evidence(value, original, rows, *, scope_complete, details_stable):
    if not isinstance(value,dict) or set(value)!=EVIDENCE_KEYS or value['version']!=1 or type(value['version']) is not int or value['detailRoute']!=DETAIL_URL or value['listRoute']!='/rest/sp-product/v0/health-infos':_refuse()
    if not isinstance(original,list) or not isinstance(rows,list) or len(rows)!=len(original):_refuse()
    before=check_list(value['listBefore']);after=check_list(value['listAfter'])
    snapshots=[]
    for key in ('detailsBefore','detailsAfter'):
        items=value[key]
        if not isinstance(items,list) or len(items)!=len(original):_refuse()
        for row,item in zip(original,items):check_detail(item,row['productId'],row['skuId'])
        snapshots.append({row['skuId']:row for row in items})
    start,end=snapshots
    stable=all(_facts(start[sku])==_facts(end[sku]) for sku in start)
    list_stable=all(before[key]==after[key] for key in ('complete','paginationComplete','schemaObserved','reportedTotal','rawRowCount')) and [_facts(v) for v in before['facts']]==[_facts(v) for v in after['facts']]
    observed=all(v['scoreObserved'] and v['issuesObserved'] and _hash(v['detailSha256']) for v in (*start.values(),*end.values()))
    agree=True;lists=[]
    for snapshot,details in ((before,start),(after,end)):
        indexed={v['skuId']:v for v in snapshot['facts']};lists.append(indexed)
        for sku,detail in details.items():
            listed=indexed.get(sku)
            if listed is not None and (not listed['scoreObserved'] or not listed['issuesObserved'] or listed['productId']!=detail['productId'] or listed['healthScore']!=detail['healthScore'] or listed['healthTitleIssue'] is not detail['healthTitleIssue'] or listed['troubleCodes']!=detail['troubleCodes']):agree=False
    verified=bool(scope_complete and details_stable and before['complete'] and after['complete'] and stable and list_stable and observed and agree)
    targets=[row for row in rows if row['target']]
    satisfied=bool(verified and targets and all(row['healthRowObserved'] and row['healthTitleIssue'] is False and row['skuId'] in lists[0] and row['skuId'] in lists[1] and end[row['skuId']]['healthTitleIssue'] is False for row in targets))
    return {'nativeHealthSourcesVerified':verified,'targetHealthRequirementsSatisfied':satisfied}


LEGACY_KEYS={'skuId','productId','productIdObserved','healthScore','healthTitleIssue','sourceSha256'}


def project_legacy_fact(data):
    """Keep the old list fact semantics, but drop all raw sourceData/private extras."""
    if not isinstance(data,dict):_refuse()
    _check_raw_privacy(data)
    sku=identifier(data.get('skuId'));has_product='productId' in data
    pid=identifier(data['productId']) if has_product else None
    score=data.get('healthScore');score=score if type(score) in (int,float) and math.isfinite(score) and 0<=score<=100 else None
    issues=data.get('improvementList');valid=isinstance(issues,list) and len(issues)<=MAX_ISSUES
    codes=[]
    if valid:
        for issue in issues:
            detail=issue.get('improvementDetail') if isinstance(issue,dict) else None
            code=detail.get('troubleCode') if isinstance(detail,dict) else None
            if not isinstance(code,str) or not 0<len(code)<=128 or any(unicodedata.category(ch).startswith('C') for ch in code) or redact(code)!=code or '://' in code:valid=False;break
            codes.append(code)
    try:sha=digest(data)
    except (ValueError,TypeError,RecursionError):_refuse()
    return {'skuId':sku,'productId':pid,'productIdObserved':has_product,'healthScore':score,
            'healthTitleIssue':'hasShortTitle' in codes if valid else None,'sourceSha256':sha}


def check_legacy_fact(value):
    if not isinstance(value,dict) or set(value)!=LEGACY_KEYS or redact(value)!=value:_refuse()
    if not isinstance(value['skuId'],str) or identifier(value['skuId'])!=value['skuId'] or type(value['productIdObserved']) is not bool:_refuse()
    if value['productIdObserved']:
        if not isinstance(value['productId'],str) or identifier(value['productId'])!=value['productId']:_refuse()
    elif value['productId'] is not None:_refuse()
    score=value['healthScore'];issue=value['healthTitleIssue']
    if score is not None and (type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=100) or issue is not None and type(issue) is not bool or not _hash(value['sourceSha256']):_refuse()
    return value


def legacy_fields(snapshot, original):
    check_list(snapshot)
    complete=bool(snapshot['paginationComplete'] and type(snapshot['reportedTotal']) is int and snapshot['reportedTotal']==snapshot['rawRowCount'] and snapshot['sourcePageHashes'])
    indexed={v['skuId']:v for v in snapshot['legacyFacts']};output={}
    for row in original:
        value=indexed.get(row['skuId']);linked=value is not None and (not value['productIdObserved'] or value['productId']==row['productId'])
        output[row['skuId']]={'healthScore':value['healthScore'] if linked else None,
                             'healthTitleIssue':value['healthTitleIssue'] if linked else None,
                             'healthRowObserved':bool(complete and linked)}
    full=complete and all(v['healthScore'] is not None and v['healthTitleIssue'] is not None and v['healthRowObserved'] for v in output.values())
    return output,{'complete':complete,'sourcePageHashes':snapshot['sourcePageHashes'],'reportedTotal':snapshot['reportedTotal'],'originalValuesComplete':bool(full)}
