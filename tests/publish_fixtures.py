"""Synthetic public-protocol shapes, never merchant authorization or writes."""
import copy,json,uuid
from pathlib import Path
from unittest.mock import patch
from heideng_merchant.operations import Operations
from heideng_merchant.materials import MaterialService
from heideng_merchant.workflows import prepare_listing
from tests import material_fixtures as media

PROFILE='merchant-publish'
CATEGORY=44207
BRAND=9001

def prop(key,value):return {'key':key,'value':value}
def component(code,value):return {'componentCode':code,'value':value}
def image(code,ref):return component(code,[{'componentCode':'img','properties':[prop('imgUrl','jfs/t1/1/synthetic.png'),prop('colorId',ref),prop('imgRefId',ref)]}])
def source_product(count=3):
 return {'title':'synthetic new product','categoryId':CATEGORY,'brandId':BRAND,'transportId':'12','customFacts':{'source':'retained'},'images':['source.png'],'skus':[{'merchantCode':'M'+str(i),'price':'30.00','stock':i,'specs':{'color':'red','size':str(i)},'extraSourceFact':i} for i in range(count)]}

def template():
 return [component('WareTitle',None),component('WareBrand',None),{'componentCode':'WareTransport','optionsValueList':[{'label':'synthetic shipping','value':'12'}]},component('WareSkuImg',None),component('WareEditor',None),{'componentCode':'SKUS','childrenComponents':[component(k,None) for k in ['SkuUUid','SkuVendorSku','SkuJdprice','SkuStockNum','SkuMainImage']]+[{'componentCode':'VenderCategoryValue','childrenComponents':[{'componentCode':'sale-prop-100','componentTitle':'color','extra':{'isColor':True,'isStructure':False,'dim':1}},{'componentCode':'sale-prop-101','componentTitle':'size','extra':{'isColor':False,'isStructure':False,'dim':2}}]}]}]

def payload(product):
 red=str(uuid.uuid4());sizes={}
 rows=[]
 for sku in product['skus']:
  size=sku['specs']['size'];sizes.setdefault(size,str(uuid.uuid4()))
  attrs=[{'componentCode':'sale-prop-100','properties':[prop('attrValueAlias','red'),prop('mappingId',red),prop('index','1')]},{'componentCode':'sale-prop-101','properties':[prop('attrValueAlias',size),prop('mappingId',sizes[size]),prop('index','2')]}]
  rows.append(component('SKU',[component('SkuUUid',str(uuid.uuid4())),component('SkuVendorSku',sku['merchantCode']),component('SkuJdprice',sku['price']),component('SkuStockNum',sku['stock']),component('VenderCategoryValue',attrs),image('SkuMainImage',red)]))
 return [component('WareTitle',product['title']),component('WareBrand',str(BRAND)),component('WareTransport','12'),image('WareSkuImg','0000000000'),component('WareEditor',[{'componentCode':'detail','properties':[prop('desc','<div><img src="https://img14.360buyimg.com/imgzone/jfs/t1/1/synthetic.png"></div>'),prop('userAgent','pc')]}]),component('SKUS',rows)]

class Client(media.Client):
 def __init__(self):
  super().__init__();self.rules=template();self.brand_revoked=False;self.validation_reply={'success':True,'data':{'wareKeeperDetectResultList':[]}};self.validation_unknown=False;self.publish_unknown=False;self.validation_posts=0;self.publish_posts=0
  self.business_categories=[{'categoryId':CATEGORY,'categoryLevel':4,'categoryName':'synthetic leaf','leafFlag':True,'selectableFlag':True,'parentCategoryId':1348},{'categoryId':1348,'categoryLevel':3,'categoryName':'synthetic third','leafFlag':False,'selectableFlag':True,'parentCategoryId':2}]
 def invoke(self,p,url,**kw):
  if url.startswith('/rest/sp-seller/') or url=='/rest/sp-product/v0/product-schemas' or url.endswith('/sale-attr-templates') or url in ('/rest/sp-product/v0/product-schemas/validations','/rest/sp-product/v0/product-applies'):
   self.calls.append((url,copy.deepcopy(kw)));params=kw.get('params',{})
   if url.endswith('/vender-categories'):
    assert params['sceneType']==3 and isinstance(params['categoryIdList'],list)
    return {'success':True,'data':copy.deepcopy(self.business_categories if params['categoryIdList']==[0] else [r for r in self.business_categories if r['categoryId'] in params['categoryIdList']])}
   if url.endswith('/vender-brands'):
    assert params['categoryId']==1348 and params['queryType']==2 and params['authStatus']==2 and params['pageSize']<=20
    rows=[] if self.brand_revoked else [{'brandId':BRAND,'brandName':'synthetic-brand','authStatus':2}]
    return {'success':True,'data':rows,'paginationData':{'totalItems':len(rows)}}
   if url=='/rest/sp-product/v0/product-schemas':
    assert params=={'lastCategoryId':CATEGORY,'scene':'pop'}
    return {'success':True,'data':[json.dumps(self.rules)]}
   if url.endswith('/sale-attr-templates'):
    assert params=={'categoryId':CATEGORY}
    return {'success':True,'data':[{'templateType':'2','templateData':json.dumps([{'attrId':100,'valueRules':json.dumps({'title':'color','items':[]})}])}]}
   assert kw['method']=='POST' and kw['write_authorized'] is True
   assert set(kw['body'])=={'scene','schema','productApplyDTO'} and kw['body']['productApplyDTO']=={'categoryDTO':{'lastCategoryId':CATEGORY}}
   if url.endswith('/validations'):
    self.validation_posts+=1
    if self.validation_unknown:raise TimeoutError('synthetic validation response loss')
    return copy.deepcopy(self.validation_reply)
   self.publish_posts+=1
   if self.publish_unknown:raise TimeoutError('synthetic publication accepted response loss')
   return {'success':True,'data':{'applyId':300,'productId':400}}
  return super().invoke(p,url,**kw)

def setup(d):
 state=Path(d);state.mkdir(exist_ok=True);client=Client();ops=Operations(state,client);ops.connect(PROFILE,'synthetic-store','1')
 src=state/'photos';src.mkdir();photo=src/'source.png';photo.write_bytes(media.png());product=source_product();package=state/'listing';manifest=prepare_listing(product,src,package)
 manifest['images'][0]['visualReview']='passed'
 # prepare_listing's new full source input is independently exercised by tests.
 from heideng_merchant.safety import atomic_json
 atomic_json(package/'manifest.json',manifest)
 with patch('heideng_merchant.materials.probe_image',side_effect=media.probe),patch('heideng_merchant.operations.probe_image',side_effect=media.probe):
  asset=MaterialService(state,client).prepare_upload(PROFILE,package/manifest['images'][0]['localPath'],'img_test',7)['task'];ops.approve(asset['taskId'],asset['fingerprint'],confirmed=True);ops.execute(asset['taskId']);MaterialService(state,client).upload_status(asset['taskId'],refresh=True)
 return client,ops,package/'manifest.json',payload(product),{'sale-prop-100':'color','sale-prop-101':'size'},[{'localPath':manifest['images'][0]['localPath'],'taskId':asset['taskId']}]
