import copy,json
from tests.test_product_schema import SchemaClient,img_component
from tests import material_fixtures as media
from heideng_merchant.operations import Operations
from heideng_merchant.product_schema import ProductSchemaService
from pathlib import Path

def setup(d,count=3):
 c=SchemaClient();c.total=count;c.product={'productId':100,'categoryDTO':{'lastCategoryId':456},'productInfo':{'productName':'synthetic original'},'material':{'mainImages':[{'colorId':'0000000000','imgRefId':'0000000000','imgUrl':'jfs/t1/1/old.png','orderSort':'1','future':{'nested':True}}]},'desc':'<div>KEEP ALL DETAILS</div>','future':{'opaque':[1,'retain']},'skuList':[]}
 rows=[];bindings=[];sale=[]
 def bind(ptr,source,sku=None,conversion='identity'):bindings.append({'schemaPointer':ptr,'sourcePointer':source,'skuId':sku,'conversion':conversion})
 schema=[{'componentCode':'WareTitle','label':'metadata retained only in capture','value':'synthetic original'},img_component('WareSkuImg','0000000000'),{'componentCode':'SKUS','value':rows},{'componentCode':'WareEditor','value':[{'componentCode':'detail','properties':[{'key':'desc','value':c.product['desc']}]}]},{'componentCode':'FutureControl','value':copy.deepcopy(c.product['future'])}]
 bind('/0/value','/productInfo/productName');bind('/4/value','/future');bind('/3/value/0/properties/0/value','/desc',conversion='html')
 def image_bind(ptr,source,sku=None):
  for i,key in enumerate(('colorId','imgRefId','imgUrl','orderSort','future')):bind(ptr+'/value/0/properties/'+str(i)+'/value',source+'/'+key,sku)
 image_bind('/1','/material/mainImages/0')
 for i in range(count):
  ident=str(2001+i);color='red' if i%2==0 else 'blue';mapping='original-'+color
  source={'skuId':int(ident),'productId':100,'outerId':'M'+str(i),'priceInfo':{'jdPrice':'30.00'},'stockNum':i,'saleAttrs':[{'attrId':100,'alias':color,'mappingId':mapping,'attrValues':'fallback-'+color,'index':'1'}],'image':{'colorId':mapping,'imgRefId':mapping,'imgUrl':'jfs/t1/1/old.png','orderSort':'1','future':{'nested':True}}};c.product['skuList'].append(source)
  fields=[{'componentCode':'SkuId','value':ident},{'componentCode':'SkuUUid','value':ident},{'componentCode':'SkuVendorSku','value':source['outerId']},{'componentCode':'SkuJdprice','value':'30.00'},{'componentCode':'SkuStockNum','value':i},{'componentCode':'VenderCategoryValue','value':[{'componentCode':'sale-prop-100','extra':{'isColor':True},'properties':[{'key':'attrValueAlias','value':color},{'key':'mappingId','value':mapping},{'key':'index','value':'1'}]}]},img_component('SkuMainImage',mapping)]
  rows.append({'componentCode':'SKU','value':fields});prefix='/2/value/'+str(i)+'/value/'
  for j,sourcepath in enumerate(('/skuId','/skuId','/outerId','/priceInfo/jdPrice','/stockNum')):bind(prefix+str(j)+'/value',sourcepath,ident,'string' if j<2 else 'identity')
  for j,key in enumerate(('alias','mappingId','index')):bind(prefix+'5/value/0/properties/'+str(j)+'/value','/saleAttrs/0/'+key,ident)
  sale.append({'skuId':ident,'componentCode':'sale-prop-100','sourcePointer':'/saleAttrs/0'});image_bind(prefix+'6','/image',ident)
 for binding in bindings:
  target=schema
  for part in binding['schemaPointer'].split('/')[1:-1]:target=target[int(part)] if isinstance(target,list) else target[part]
  target['productDetailField']=('skuList.' if binding['skuId'] is not None else '')+'.'.join(binding['sourcePointer'].split('/')[1:])
 c.schema=schema;ops=Operations(d,c);ops.connect('merchant-test','synthetic-store','1');capture=ProductSchemaService(d,c).capture_edit('merchant-test','100')
 return c,ops,capture,bindings,sale
