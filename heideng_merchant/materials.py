"""Native POP image spaces, categories, uploads and receipt-bound storage readback."""
from __future__ import annotations
import base64,hashlib,time
from pathlib import Path
from .operations import Operations,digest
from .safety import SafetyError,redact,is_linked
from .verification import business_payload,pagination_total
from .result_verification import resource_id
from .material_contract import ZONES,CATEGORIES,IMAGES,IMAGE_DETAIL,SKILL,MAX_BASE64_BYTES,category_id,image_name,expected_verification
from .official_transport import matches_shop
from .image_probe import probe_image

_FILTERS={CATEGORIES:{'categoryIdSet','categoryName','parentCategoryId'},IMAGES:{'categoryId','imgName','imgType','widthBegin','widthEnd','heightBegin','heightEnd','createdTimeBeginTime','createdTimeEndTime','useFlag','sepWordFlag','sortBy','sortOrder'}}

def _filters(url,value):
 if value is None:return {}
 if not isinstance(value,dict) or set(value)-_FILTERS[url] or redact(value)!=value:raise SafetyError('unreviewed-or-sensitive-material-query-fields')
 for key,val in value.items():
  if key=='categoryIdSet':
   if not isinstance(val,list) or not val or len(val)>1000:raise SafetyError('bounded-category-id-list-required')
   for item in val:category_id(item)
  elif not isinstance(val,(str,int,float,bool)) or len(str(val))>1024:raise SafetyError('scalar-native-material-filter-required')
 return dict(value)

class MaterialService:
 def __init__(self,state,client):self.state=Path(state).resolve();self.client=client;self.ops=Operations(self.state,client)
 def _read(self,profile,url,params):
  shop=self.ops.shop(profile)
  if not matches_shop(self.client.identity(profile),shop):raise SafetyError('material-read-shop-mismatch')
  result=self.client.invoke(profile,url,method='GET',params=params,skill_id=SKILL)
  if not matches_shop(self.client.identity(profile),shop):raise SafetyError('material-read-shop-changed')
  return result
 def zones(self,profile,*,zone_type=None):
  if zone_type is not None and (isinstance(zone_type,bool) or zone_type not in (1,2)):raise SafetyError('native-zone-type-one-or-two-required')
  result=self._read(profile,ZONES,{} if zone_type is None else {'zoneType':zone_type});rows=business_payload(result)
  if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise SafetyError('native-zone-array-required')
  ids=[resource_id(row.get('zoneId')) for row in rows]
  if len(set(ids))!=len(ids) or any(str(row.get('zoneType')) not in ('1','2') for row in rows):raise SafetyError('native-zone-id-or-type-ambiguous')
  selected=rows if zone_type is None else [r for r in rows if str(r['zoneType'])==str(zone_type)]
  return {'items':selected,'complete':True,'source':'official-realtime-pop','sourceSha256':digest(result),'profile':profile,'observedAt':time.time()}
 def _zone(self,profile,zone):
  zone=resource_id(zone);rows=self.zones(profile)['items'];matches=[r for r in rows if str(r['zoneId'])==zone]
  if len(matches)!=1 or str(matches[0]['zoneType'])!='1':raise SafetyError('actual-owned-image-zone-required')
  return zone
 def categories(self,profile,zone,*,filters=None,page_size=50,max_pages=100,start_page=1):
  filters=_filters(CATEGORIES,filters);zone=self._zone(profile,zone)
  return self._pages(profile,CATEGORIES,'categoryId',zone,filters,page_size,max_pages,start_page)
 def images(self,profile,zone,*,filters=None,page_size=50,max_pages=100,start_page=1):
  filters=_filters(IMAGES,filters);zone=self._zone(profile,zone)
  return self._pages(profile,IMAGES,'imgId',zone,filters,page_size,max_pages,start_page)
 def detail(self,profile,zone,image_id):
  zone=self._zone(profile,zone);image_id=resource_id(image_id);response=self._read(profile,IMAGE_DETAIL,{'zoneId':zone,'imageId':image_id,'getReferenceFlag':True});data=business_payload(response)
  if not isinstance(data,dict) or resource_id(data.get('imgId'))!=image_id:raise SafetyError('native-image-detail-id-mismatch')
  return data
 def _pages(self,profile,url,key,zone,filters,page_size,max_pages,start_page):
  if any(isinstance(v,bool) or not isinstance(v,int) for v in (page_size,max_pages,start_page)) or not 1<=page_size<=100 or not 1<=max_pages<=1000 or start_page<1:raise SafetyError('bounded-material-pagination-required')
  rows=[];seen=set();total=None;hashes=[];end=False;next_page=start_page;reason='page-budget-reached'
  for page in range(start_page,start_page+max_pages):
   try:
    response=self._read(profile,url,{'zoneId':zone,**filters,'page':page,'pageSize':page_size});data=business_payload(response)
    if not isinstance(data,list) or any(not isinstance(row,dict) for row in data):raise SafetyError('native-material-page-array-required')
    ids=[str(category_id(row.get(key))) if key=='categoryId' else resource_id(row.get(key)) for row in data];new_total=pagination_total(response)
   except Exception:
    if not rows:raise SafetyError('native-material-read-incomplete') from None
    reason='native-material-read-incomplete';next_page=page;break
   if len(set(ids))!=len(ids) or seen.intersection(ids):reason='pagination-identity-repeat';next_page=page;break
   if new_total is not None:
    if total is not None and new_total!=total:reason='pagination-total-changed';next_page=page;break
    total=new_total
   rows.extend(data);seen.update(ids);hashes.append(digest(response));next_page=page+1
   if new_total is None:reason='pagination-metadata-missing';next_page=page;break
   remaining=max(total-(start_page-1)*page_size,0) if total is not None else None
   if remaining is not None and len(rows)==remaining:end=True;next_page=None;reason=None;break
   if remaining is not None and len(rows)>remaining:reason='pagination-total-mismatch';break
   if not data or (total is None and len(data)<page_size):
    end=total is None or len(rows)==remaining;next_page=None if end else page+1;reason=None if end else 'pagination-total-incomplete';break
  if end and start_page>1:reason='earlier-pages-not-in-this-result'
  return {'items':rows,'complete':end and start_page==1,'segmentComplete':end,'startPage':start_page,'nextPage':next_page,'reason':reason,'reportedTotal':total,'sourcePageHashes':hashes,'profile':profile,'zoneId':zone,'source':'official-realtime-pop','observedAt':time.time()}
 def prepare_upload(self,profile,image,zone,category,*,name=None):
  path=Path(image).absolute()
  if not path.is_file() or any(is_linked(p) for p in (path,*path.parents)):raise SafetyError('actual-unlinked-image-file-required')
  if path.stat().st_size<=0 or ((path.stat().st_size+2)//3)*4>=MAX_BASE64_BYTES:raise SafetyError('base64-encoded-image-must-be-under-3MB')
  raw=path.read_bytes();encoded=base64.b64encode(raw).decode('ascii')
  if len(encoded)>=MAX_BASE64_BYTES:raise SafetyError('base64-encoded-image-must-be-under-3MB')
  info=probe_image(self.state,raw);zone=resource_id(zone);category=category_id(category);name=image_name(name or path.name)
  op={'url':IMAGES,'method':'POST','params':{'zoneId':zone},'body':{'imgBase64':encoded,'zoneImageDTO':{'imgName':name,'categoryId':category}},'skillId':SKILL}
  verification=expected_verification(zone,category,name,info['width'],info['height']);task=self.ops.prepare(profile,op,result_verification=verification)
  return {'task':task,'image':info,'zoneId':zone,'categoryId':category,'requiresApproval':task['status']=='prepared','productBound':False,'source':'local-original-image-bytes'}
 def upload_status(self,task_id,*,refresh=False):
  task=self.ops.task(task_id)
  if 'materialUpload' not in task['scope']:raise SafetyError('native-image-upload-task-required')
  if task['status']=='unknown':return {'task':task,'phase':'unknown','storageVerified':False,'productBound':False,'remotePixelsVerified':False}
  if refresh and task['status'] in ('submitted','verified'):task=self.ops.verify_result(task_id)
  verified=bool(refresh and task.get('resultStateVerified'))
  phase='remote-storage-fields-verified' if verified else ('verified-historical-recheck-before-use' if task['status']=='verified' else task['status'])
  asset=business_payload(task['result']) if task.get('result') else None
  return {'task':task,'phase':phase,'storageVerified':verified,'productBound':False,'remotePixelsVerified':False,'asset':asset,'originalSha256':task['scope']['materialUpload']['image']['sha256']}
