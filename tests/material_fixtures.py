"""Synthetic valid PNG and an in-memory media API; never real merchant requests."""
import base64,copy,hashlib,struct,zlib

def png():
 def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0'+b'\x80\x80\x80'*2+b'\0'+b'\x80\x80\x80'*2))+chunk(b'IEND',b'')

def probe(state,raw):return {'sha256':hashlib.sha256(raw).hexdigest(),'format':'PNG','width':2,'height':2,'bytes':len(raw),'frames':1}

def upload_scope():
 op={'url':'/rest/sp-product/v0/media-zones/{zoneId}/images','method':'POST','params':{'zoneId':'img_test'},'body':{'imgBase64':base64.b64encode(png()).decode(),'zoneImageDTO':{'imgName':'sample.png','categoryId':7}},'skillId':'jdo-product-material'}
 verify={'query':{'url':'/rest/sp-product/v0/media-zones/{zoneId}/images/{imageId}','params':{'zoneId':'img_test','imageId':{'$result':'imgId'}},'skillId':'jdo-product-material'},'expected':{'imgId':{'$result':'imgId'},'categoryId':7,'imgName':'sample.png','imgWidth':2,'imgHeight':2}}
 return op,verify

class Client:
 def __init__(self):
  self.calls=[];self.foreign=False;self.unknown=False;self.zones=[{'zoneId':'img_test','zoneType':1}];self.categories=[{'categoryId':7,'categoryName':'synthetic-category','status':1}];self.images=[];self.bad_ack=None
 def identity(self,p):return {'venderId':'2' if self.foreign else '1','shopId':'3','shopName':'synthetic-store','shopType':'POP'}
 def invoke(self,p,url,**kw):
  self.calls.append((url,copy.deepcopy(kw)));params=kw.get('params',{})
  if kw.get('method','GET')=='POST':
   assert url=='/rest/sp-product/v0/media-zones/{zoneId}/images' and params['zoneId']=='img_test'
   dto=kw['body']['zoneImageDTO'];row={'imgId':'asset-'+str(len(self.images)+1),'imgUrl':'jfs/t1/1/synthetic.png','imgName':dto['imgName'],'categoryId':dto['categoryId'],'imgWidth':2,'imgHeight':2,'imgType':'PNG','imgSize':len(base64.b64decode(kw['body']['imgBase64']))};self.images.append(row)
   if self.unknown:raise TimeoutError('synthetic accepted but response lost')
   return {'success':True,'data':copy.deepcopy(self.bad_ack or row)}
  if url.endswith('/categories'):
   selected=self.categories
   if params.get('categoryIdSet'):selected=[r for r in selected if r['categoryId'] in params['categoryIdSet']]
  elif '{imageId}' in url:return {'data':copy.deepcopy(next((r for r in self.images if r['imgId']==params['imageId']),{}))}
  elif url.endswith('/images'):selected=self.images
  else:return {'data':copy.deepcopy(self.zones)}
  size=params['pageSize'];page=params['page'];return {'data':copy.deepcopy(selected[(page-1)*size:page*size]),'paginationData':{'totalItems':len(selected)}}
