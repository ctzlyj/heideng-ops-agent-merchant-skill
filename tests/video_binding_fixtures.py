"""Synthetic product/video/material/relation boundary, never a real shop."""
import copy
from .video_delivery_fixtures import Client as VideoClient
from .test_sku_materials import Client as SkuClient
TAGS='/rest/sp-product/v0/sku-material-tags'
RELS='/rest/sp-product/v0/media-zones/{zoneId}/video-sku-rels'
class Client(VideoClient):
 def __init__(self,count=3):
  super().__init__();self.native=SkuClient(count);self.skus=self.native.skus;self.materials=self.native.materials;self.posts=self.native.posts;self.binding_fault=None;self.tags=[{'tagId':17,'sort':2,'tagName':'产品展示'}];self.relation_pages=[];self.relation_status_override={}
 def invoke(self,p,url,**kw):
  if url.endswith('/apis/{apiname}') and kw['params']['apiname'] in ('GET.sp-product.v0.sku-material-tags','GET.sp-product.v0.media-zones._zoneId.video-sku-rels'):
   api=kw['params']['apiname'];path=TAGS if api.endswith('sku-material-tags') else RELS
   fields={'materialType':{'type':'integer','const':42},'secondCategoryId':{'type':'integer'}} if path==TAGS else {'zoneId':{'type':'string'},'videoType':{'type':'integer','const':42},'videoIds':{'type':'array','items':{'type':'integer'},'maxItems':10},'page':{'type':'integer'},'pageSize':{'type':'integer'},'scopeSet':{'type':'array','items':{'type':'string','const':'BASE'}}}
   schema={'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}
   if self.binding_fault=='card':schema['$ref']='#/not-reviewed'
   return {'data':{'apiName':api,'method':'GET','path':path,'inputSchema':schema}}
  if url==TAGS:return {'data':copy.deepcopy(self.tags)}
  if url==RELS:
   q=kw['params'];self.relation_pages.append(q['page']);rows=[]
   for sku,materials in self.materials.items():
    for m in materials:
     if m['materialType']==42 and m['order']==1 and m['videoMaterial']['videoId'] in q['videoIds']:
      rows.append({'videoType':42,'videoId':m['videoMaterial']['videoId'],'jdVideoId':m['videoMaterial']['jdVideoId'],'productId':9,'skuId':int(sku),'relationStatus':self.relation_status_override.get(sku,m['status'])})
   rows.sort(key=lambda r:r['skuId']);total=len(rows);page=rows[(q['page']-1)*q['pageSize']:q['page']*q['pageSize']]
   if self.binding_fault=='relation-duplicate' and page:page.append(copy.deepcopy(page[0]))
   if self.binding_fault=='relation-total':total+=q['page']
   if self.binding_fault=='relation-missing':page=[]
   return {'data':page,'paginationData':{'totalItems':total}}
  native=url.endswith('/products/{productId}') or url.endswith('/skus') or url.startswith('/rest/sp-product/v0/sku-materials') or url.endswith('/apis/{apiname}') and kw['params']['apiname'] in ('GET.sp-product.v0.sku-materials','POST.sp-product.v0.sku-materials.batch')
  if native:
   self.native.fault=self.binding_fault if self.binding_fault in ('timeout','omitted','duplicate','foreign','partial') else None
   result=self.native.invoke(p,url,**kw)
   if url.endswith('/products/{productId}'):result['data']['categoryDetail']={'secondCategoryId':12,'lastCategoryId':13}
   return result
  return super().invoke(p,url,**kw)
