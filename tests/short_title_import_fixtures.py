"""Synthetic merchant browser for native short-title upload/create; no real network."""
from pathlib import Path
from tests import test_short_title_browser as base

UPLOAD='https://api.m.jd.com/api?method=file.upload'
CREATE='https://api.m.jd.com/api?method=batchJobService.createImportJob'

class ImportLocator(base.Locator):
 def locator(self,selector):return ImportLocator(self.page,'file' if selector=='input[type=file]' else 'drawer' if 'drawer' in selector else 'element')
 def get_by_role(self,role,**kw):return ImportLocator(self.page,'link' if role=='link' else 'create' if kw.get('name')=='确定导入' else 'button')
 def get_by_text(self,text,**kw):return ImportLocator(self.page,'open' if text=='批量设置短标题' else 'label')
 def count(self):return self.page.file_count if self.kind=='file' else super().count()
 def set_input_files(self,path,**kw):
  self.page.uploads+=1;self.page.selected=Path(path).name;self.page.upload_sha=__import__('hashlib').sha256(Path(path).read_bytes()).hexdigest();self.page.upload_url='https://storage.jd.com/synthetic/'+self.page.selected+'?token=synthetic-only-private'
  if self.page.fault=='upload-timeout':return
  value={'code':400,'data':None} if self.page.fault=='upload-refused' else {'code':200,'data':{'url':self.page.upload_url}}
  self.page.emit(base.Response(self.page,UPLOAD,value))
 def wait_for(self,**kw):
  if self.kind=='label' and not self.page.selected:raise RuntimeError('synthetic upload label unavailable')
 def click(self,**kw):
  if self.kind!='create':return super().click(**kw)
  self.page.creates+=1;instance=str(7000000000+self.page.creates);self.page.tasks['data']['batchJobRecordDtoList'].append({'jobExecId':instance,'jobId':'30034','jobExecFileSrc':self.page.upload_url,'jobExecTimeStart':1000})
  if self.page.fault=='create-timeout':return
  value={'code':400,'data':None} if self.page.fault=='create-refused' else {'code':200,'data':{'jobId':'30034'}} if self.page.fault=='type-id-only' else {'code':200,'data':{'taskInstanceId':instance,'jobId':'30034'}}
  self.page.emit(base.Response(self.page,CREATE,value))

class ImportPage(base.Page):
 def __init__(self,temp):super().__init__(temp);self.uploads=0;self.creates=0;self.file_count=1;self.fault=None;self.selected=None;self.upload_url=None;self.upload_sha=None
 def locator(self,selector):return ImportLocator(self,'drawer' if 'drawer' in selector else 'element')
 def get_by_text(self,*args,**kw):return ImportLocator(self,'open')
 def goto(self,url,**kw):self.selected=None;return super().goto(url,**kw)
class ImportContext(base.Context):
 def new_page(self):self.page=ImportPage(self.temp);self.pages.append(self.page);return self.page
class ImportFactory(base.Factory):
 def __init__(self,temp):super().__init__(temp);self.driver.context=ImportContext(temp)
