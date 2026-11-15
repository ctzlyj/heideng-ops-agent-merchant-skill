"""Native video operation/card contracts; no media generation or credentials."""
import json,re
from .safety import SafetyError,redact
from .verification import business_payload,pagination_total
from .result_verification import resource_id
from .official_transport import matches_shop

ZONES='/rest/sp-product/v0/media-zones'
ALLOC=ZONES+'/{zoneId}/upload-urls'
VIDEOS=ZONES+'/{zoneId}/videos'
SKILL='jdo-api-830'
API={ALLOC:('GET.sp-product.v0.media-zones._zoneId.upload-urls','GET'),VIDEOS:('POST.sp-product.v0.media-zones._zoneId.videos','POST'),'read':('GET.sp-product.v0.media-zones._zoneId.videos','GET')}


def guarded_video_route(url,method):
    canonical='/'+ '/'.join(p for p in url.split('/') if p and p!='.')
    return bool(re.fullmatch(r'/rest/sp-product/v0/media-zones/(?:[A-Za-z0-9_-]+|\{[A-Za-z0-9_]+\})/upload-urls',canonical) or method!='GET' and re.fullmatch(r'/rest/sp-product/v0/media-zones/(?:[A-Za-z0-9_-]+|\{[A-Za-z0-9_]+\})/videos(?:/.*)?',canonical))


def native_id(value):
    if isinstance(value,bool) or not isinstance(value,(int,str)) or not re.fullmatch('[1-9][0-9]{0,18}',str(value)) or int(value)>2**63-1:raise SafetyError('original-native-video-positive-int64-id-required')
    return str(value)


def read(client,shop,url,params):
    if not matches_shop(client.identity(shop['profile']),shop):raise SafetyError('native-video-shop-mismatch')
    result=client.invoke(shop['profile'],url,method='GET',params=params,skill_id=SKILL)
    if not matches_shop(client.identity(shop['profile']),shop):raise SafetyError('native-video-shop-changed-during-read')
    business_payload(result);return result


def zone(client,shop,zone_id):
    zone_id=resource_id(zone_id);data=business_payload(read(client,shop,ZONES,{'zoneType':2}))
    if not isinstance(data,list) or any(not isinstance(row,dict) for row in data):raise SafetyError('native-video-zone-list-required')
    ids=[resource_id(row.get('zoneId')) for row in data]
    selected=[row for row in data if str(row['zoneId'])==zone_id]
    if len(ids)!=len(set(ids)) or len(selected)!=1 or str(selected[0].get('zoneType'))!='2':raise SafetyError('actual-owned-video-zone-required')
    row=selected[0]
    if 'venderId' in row and str(row['venderId'])!=shop['venderId']:raise SafetyError('foreign-video-zone-refused')
    return {'zoneId':zone_id,'zoneType':2}


def card(client,shop,key):
    from .sku_material_contract import hash_value
    api,method=API[key];path=VIDEOS if key=='read' else key
    data=business_payload(read(client,shop,'/rest/open-metadata/v0/apis/{apiname}',{'apiname':api}))
    if not isinstance(data,dict) or data.get('apiName')!=api or data.get('method')!=method or data.get('path') not in (path,path.removeprefix('/rest')):raise SafetyError('native-video-capability-route-mismatch')
    schema=data.get('inputSchema')
    if isinstance(schema,str):
        def unique(pairs):
            result={}
            for k,v in pairs:
                if k in result:raise SafetyError('duplicate-native-video-schema-key')
                result[k]=v
            return result
        try:schema=json.loads(schema,object_pairs_hook=unique)
        except (TypeError,ValueError):raise SafetyError('native-video-schema-unreadable') from None
    required=({'zoneId','videoType','scopeSet','videoIdSet'} if key=='read' else {'zoneId','fileName','fileSize','videoType'} if key==ALLOC else {'zoneId','zoneVideoDTO'})
    if not isinstance(schema,dict) or schema.get('type')!='object' or not required<=set(schema.get('properties',{})) or redact(schema)!=schema:raise SafetyError('native-video-schema-needs-reviewed-adapter')
    return {'apiName':api,'method':method,'path':path,'inputSchema':schema,'cardSha256':hash_value({'apiName':api,'method':method,'path':path,'inputSchema':schema})}


def validate_input(card,params,body=None):
    from .sku_material_contract import validate_schema
    value=dict(params)
    if body is not None:
        if set(params).intersection(body):raise SafetyError('native-video-params-body-field-collision')
        value.update(body)
    validate_schema(value,card['inputSchema'])


def id_value(schema,value):
    value=native_id(value);kind=schema.get('type') if isinstance(schema,dict) else None
    if kind=='integer':return int(value)
    if kind=='string':return value
    raise SafetyError('native-video-id-schema-needs-reviewed-adapter')
