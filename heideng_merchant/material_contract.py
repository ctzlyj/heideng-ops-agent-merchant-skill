"""Mandatory native media upload contract, including the generic task entrypoint."""
import base64,hashlib,re
from .safety import SafetyError
from .result_verification import resource_id
from .verification import business_payload
from .official_transport import matches_shop

ZONES='/rest/sp-product/v0/media-zones'
CATEGORIES=ZONES+'/{zoneId}/categories'
IMAGES=ZONES+'/{zoneId}/images'
IMAGE_DETAIL=IMAGES+'/{imageId}'
SKILL='jdo-product-material'
MAX_BASE64_BYTES=3_000_000

def category_id(value):
 if isinstance(value,bool) or not isinstance(value,(int,str)) or not re.fullmatch(r'-?[0-9]{1,19}',str(value)) or not -(2**63)<=int(value)<2**63:raise SafetyError('actual-native-int64-category-id-required')
 return int(value)

def image_name(value):
 if not isinstance(value,str) or not value.strip() or len(value)>128 or value!=value.strip() or value!=value.rstrip(' .') or any(c in value for c in '/\\:<>"|?*') or any(ord(c)<32 for c in value):raise SafetyError('safe-image-name-required')
 suffix=value.rsplit('.',1)[-1].lower()
 if suffix not in ('png','jpg','jpeg','gif','webp'):raise SafetyError('native-supported-image-suffix-required')
 return value

def expected_verification(zone,category,name,width,height):
 return {'query':{'url':IMAGE_DETAIL,'method':'GET','params':{'zoneId':zone,'imageId':{'$result':'imgId'}},'skillId':SKILL},'expected':{'imgId':{'$result':'imgId'},'categoryId':category,'imgName':name,'imgWidth':width,'imgHeight':height}}

def describe_upload(scope):
 op=scope['operation'];url='/'+('/'.join(part for part in op['url'].split('/') if part and part!='.'))
 if op['method']!='POST' or not re.fullmatch(r'/rest/sp-product/v0/media-zones/(?:[A-Za-z0-9_-]+|\{zoneId\})/images',url):return None
 if op['url']!=IMAGES or op['skillId']!=SKILL or set(op['params'])!={'zoneId'}:raise SafetyError('canonical-native-image-upload-scope-required')
 zone=resource_id(op['params']['zoneId']);body=op.get('body')
 if not isinstance(body,dict) or set(body)!={'imgBase64','zoneImageDTO'}:raise SafetyError('native-base64-and-zoneImageDTO-required-fileUrl-needs-invited-adapter')
 dto=body['zoneImageDTO']
 if not isinstance(dto,dict) or set(dto)!={'imgName','categoryId'} or not isinstance(dto['categoryId'],int) or isinstance(dto['categoryId'],bool):raise SafetyError('native-image-name-and-int64-category-required')
 category=category_id(dto['categoryId']);name=image_name(dto['imgName']);encoded=body['imgBase64']
 if not isinstance(encoded,str) or not encoded or len(encoded)>=MAX_BASE64_BYTES:raise SafetyError('native-base64-size-invalid')
 try:raw=base64.b64decode(encoded,validate=True)
 except (ValueError,TypeError):raise SafetyError('native-base64-invalid-no-data-uri') from None
 if not raw:raise SafetyError('empty-native-image-source')
 verification=scope.get('resultVerification');expected=verification.get('expected',{}) if isinstance(verification,dict) else {}
 width=expected.get('imgWidth');height=expected.get('imgHeight')
 if any(isinstance(x,bool) or not isinstance(x,int) or x<=0 for x in (width,height)) or verification!=expected_verification(zone,category,name,width,height) or any(key in scope for key in ('verification','onlineVerification','precondition')):raise SafetyError('complete-native-image-result-bound-verification-required')
 descriptor={'zoneId':zone,'categoryId':category,'imgName':name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'width':width,'height':height}
 return descriptor,raw

def check_image_evidence(descriptor,info):
 if not isinstance(info,dict) or info.get('sha256')!=descriptor['sha256'] or info.get('bytes')!=descriptor['bytes'] or info.get('width')!=descriptor['width'] or info.get('height')!=descriptor['height']:raise SafetyError('native-image-decode-evidence-does-not-match-approved-source')
 suffix=descriptor['imgName'].rsplit('.',1)[-1].upper();suffix='JPG' if suffix=='JPEG' else suffix
 if info.get('format')!=suffix:raise SafetyError('image-format-does-not-match-file-name')

def _native_read(client,shop,url,params):
 if not matches_shop(client.identity(shop['profile']),shop):raise SafetyError('native-material-shop-mismatch')
 response=client.invoke(shop['profile'],url,method='GET',params=params,skill_id=SKILL)
 if not matches_shop(client.identity(shop['profile']),shop):raise SafetyError('native-material-shop-changed-during-read')
 return response

def verify_upload_context(client,shop,descriptor):
 zones=_native_read(client,shop,ZONES,{'zoneType':1});rows=business_payload(zones)
 if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise SafetyError('native-material-zone-array-required')
 ids=[resource_id(r.get('zoneId')) for r in rows]
 if len(set(ids))!=len(ids):raise SafetyError('native-material-zone-id-ambiguous')
 matches=[r for r in rows if str(r['zoneId'])==descriptor['zoneId']]
 if len(matches)!=1 or str(matches[0].get('zoneType'))!='1':raise SafetyError('actual-owned-image-zone-required')
 categories=_native_read(client,shop,CATEGORIES,{'zoneId':descriptor['zoneId'],'categoryIdSet':[descriptor['categoryId']],'page':1,'pageSize':50});rows=business_payload(categories)
 if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise SafetyError('native-material-category-array-required')
 ids=[category_id(r.get('categoryId')) for r in rows]
 if len(set(ids))!=len(ids):raise SafetyError('native-material-category-id-ambiguous')
 matches=[r for r in rows if category_id(r.get('categoryId'))==descriptor['categoryId']]
 if len(matches)!=1 or str(matches[0].get('status'))!='1':raise SafetyError('actual-owned-active-image-category-required')
 return {'zones':zones,'categories':categories}

def validate_image_receipt(descriptor,info,response,*,original=None):
 data=business_payload(response)
 if not isinstance(data,dict):raise SafetyError('native-image-receipt-object-required')
 image_id=resource_id(data.get('imgId'));url=data.get('imgUrl')
 if not isinstance(url,str) or not re.fullmatch(r'jfs/[A-Za-z0-9_./-]{1,2000}',url) or '..' in url:raise SafetyError('native-image-jfs-path-required')
 if data.get('imgName')!=descriptor['imgName'] or category_id(data.get('categoryId'))!=descriptor['categoryId'] or any(isinstance(data.get(k),bool) or not str(data.get(k)).isdigit() or int(data[k])!=info[field] for k,field in (('imgWidth','width'),('imgHeight','height'))):raise SafetyError('native-image-receipt-fields-mismatch')
 fmt=str(data.get('imgType','')).upper();fmt='JPG' if fmt=='JPEG' else fmt
 if fmt!=info['format'] or isinstance(data.get('imgSize'),bool) or not str(data.get('imgSize')).isdigit() or int(data['imgSize'])<=0:raise SafetyError('native-image-receipt-format-or-size-invalid')
 if original is not None:
  first=business_payload(original)
  size=first.get('imgSize')
  if image_id!=resource_id(first.get('imgId')) or url!=first.get('imgUrl') or isinstance(size,bool) or not str(size).isdigit() or int(data['imgSize'])!=int(size):raise SafetyError('native-image-readback-differs-from-original-receipt')
 return data
