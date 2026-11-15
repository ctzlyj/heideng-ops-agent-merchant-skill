"""Synthetic native allocator/save/list with no merchant auth or network."""
import copy,uuid
from .material_fixtures import Client as Base
from heideng_merchant.video_contract import ALLOC,VIDEOS,ZONES,API
from heideng_merchant.video_transfer import UploadGrant
from heideng_merchant.safety import SafetyError

class Client(Base):
 def __init__(self,size=0):
  super().__init__();self.video_size=size;self.allocations=[];self.saves=[];self.transfers=[];self.video=None;self.secret=uuid.uuid4().hex;self.fault=None
 def plan_execution(self,operation,*,profile):return {'transport':'official-source-stdin','officialVersion':'0.3.7','sourceSha256':'a'*64}
 def allocate_video_upload(self,profile,params,**kw):
  self.allocations.append(copy.deepcopy(params))
  if self.fault=='allocation-timeout':raise SafetyError('synthetic unknown allocation')
  jd=(params.get('jdVideoId') if params.get('breakPointFlag') else 899+sum('breakPointFlag' not in p for p in self.allocations))
  if self.fault=='wrong-renewed-id' and params.get('breakPointFlag'):jd=int(jd)+1
  return UploadGrant(jd,'https://upload.example.test/file?grant='+self.secret)
 def transfer(self,grant,path,sha,size,deadline,**kw):
  if self.fault=='before-transfer':
   from heideng_merchant.video_transfer import TransferNotDispatched
   raise TransferNotDispatched('synthetic no HTTP launch')
  if kw.get('before_dispatch'):kw['before_dispatch']()
  jd,url=grant.consume();self.transfers.append(jd)
  if self.fault=='transfer-timeout':raise SafetyError('synthetic unknown transfer')
  return {'jdVideoId':jd,'httpStatus':200,'sentBytes':size,'originalSha256':sha,'responseSha256':'a'*64,'responseBytes':2,'singleAttempt':True,'storageVerified':False}
 def invoke(self,profile,url,**kw):
  if url==ZONES:return {'data':[{'zoneId':'video-owned','zoneType':2,'venderId':'2' if self.fault=='zone' else '1'}]}
  if url.endswith('/apis/{apiname}') and kw['params'].get('apiname') in [v[0] for v in API.values()]:
   api=kw['params']['apiname'];key=next(k for k,v in API.items() if v[0]==api);method=API[key][1];path=VIDEOS if key=='read' else key;fields={'zoneId':{'type':'string'}}
   if key==ALLOC:fields.update(fileName={'type':'string'},fileSize={'type':'integer'},videoType={'type':'integer','const':1},jdVideoId={'type':'integer'},breakPointFlag={'type':'boolean'});required=['zoneId','fileName','fileSize','videoType']
   elif key=='read':fields.update(videoType={'type':'integer','const':1},scopeSet={'type':'array','items':{'type':'string','const':'BASE'}},page={'type':'integer'},pageSize={'type':'integer'},videoIdSet={'type':'array','items':{'type':'integer'}},jdVideoIdSet={'type':'array','items':{'type':'integer'}});required=['zoneId','videoType','scopeSet']
   else:fields['zoneVideoDTO']={'type':'object','properties':{'videoName':{'type':'string','maxLength':18},'videoDesc':{'type':'string'},'videoType':{'type':'integer','const':1},'videoSize':{'type':'integer'},'jdVideoId':{'type':'integer'}},'required':['videoName','videoDesc','videoType','videoSize','jdVideoId'],'additionalProperties':False};required=['zoneId','zoneVideoDTO']
   schema={'type':'object','properties':fields,'required':required,'additionalProperties':False}
   if self.fault=='card':schema['$ref']='#/unsupported'
   return {'data':{'apiName':api,'method':method,'path':path,'inputSchema':schema}}
  if url==VIDEOS and kw.get('method')=='POST':
   body=copy.deepcopy(kw['body']);self.saves.append(body);dto=body['zoneVideoDTO'];self.video={'videoId':699+len(self.saves),'jdVideoId':dto['jdVideoId'],'videoName':dto['videoName'],'videoDesc':dto['videoDesc'],'videoSize':dto['videoSize'],'videoType':1,'duration':1,'status':2,'indexImage':'jfs/synthetic/video-index.png','playUrlList':[]}
   if self.fault=='save-timeout':raise SafetyError('synthetic unknown save')
   return {'success':True,'data':{'videoId':self.video['videoId'],'jdVideoId':dto['jdVideoId']}}
  if url==VIDEOS:
   rows=[copy.deepcopy(self.video)] if self.video else []
   if rows and self.fault=='readback-id':rows[0]['jdVideoId']=999
   if rows and self.fault=='audit-pending':rows[0]['status']=3
   if rows and self.fault=='rejected':rows[0]['status']=5
   return {'data':rows,'paginationData':{'totalItems':len(rows)}}
  return super().invoke(profile,url,**kw)
