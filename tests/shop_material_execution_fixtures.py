"""Synthetic multi-product native shop; no real auth, network, or generators."""
import copy
from tests.test_shop_material_audit import ShopClient,PRODUCTS
from tests.test_sku_materials import material,WRITE
class Client(ShopClient):
 def __init__(self,first=53,second=3):
  super().__init__();self.products=[{'productId':9,'productName':'synthetic-one','productStatus':103},{'productId':10,'productName':'synthetic-two','productStatus':103},{'productId':20,'productName':'synthetic-offsale','productStatus':104}]
  self.skus=[{'skuId':101+i,'productId':9,'status':103,'skuName':'synthetic-a-'+str(i)} for i in range(first)]+[{'skuId':1001+i,'productId':10,'status':103,'skuName':'synthetic-b-'+str(i)} for i in range(second)]+[{'skuId':9001,'productId':9,'status':104,'skuName':'synthetic-off-a'},{'skuId':9002,'productId':10,'status':104,'skuName':'synthetic-off-b'},{'skuId':301,'productId':20,'status':103,'skuName':'synthetic-off-product'}]
  self.health=[{'skuId':s['skuId'],'productId':s['productId'],'healthScore':0 if s['skuId']==101 else 100,'improvementList':[]} for s in self.skus if s['status']==103 and s['productId']!=20];self.health=self.health[:-1]
  self.materials={str(s['skuId']):[material(s['skuId'])] for s in self.skus};self.write_fault_on=None
 def invoke(self,p,url,**kw):
  q=kw.get('params',{})
  if url==PRODUCTS and 'productIdList' in q:
   self.product_reads+=1;rows=[r for r in self.products if r['productId'] in q['productIdList'] and r['productStatus'] in q.get('productStatusList',[103])];size=q['pageSize'];start=(q['page']-1)*size
   return {'data':copy.deepcopy(rows[start:start+size]),'paginationData':{'totalItems':len(rows)}}
  if url.endswith('/products/{productId}'):
   pid=int(q['productId']);product=next(r for r in self.products if r['productId']==pid);return {'data':{'productId':pid,'productStatus':product['productStatus'],'skuList':copy.deepcopy([r for r in self.skus if r['productId']==pid])}}
  if url==WRITE and self.write_fault_on==len(self.posts)+1:self.fault='timeout'
  return super().invoke(p,url,**kw)
def changes(client):
 return [{'productId':s['productId'],'skuId':s['skuId'],'slot':'point1','text':'轻巧便携','review':'passed'} for s in client.skus if s['status']==103 and s['productId']!=20]
