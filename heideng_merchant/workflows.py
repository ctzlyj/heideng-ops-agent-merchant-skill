"""Deterministic merchant business preparation; no generation or employee data."""
from __future__ import annotations
import csv,hashlib,json,re,shutil,unicodedata,urllib.parse,urllib.request,uuid
from decimal import Decimal,InvalidOperation
from pathlib import Path
from .safety import SafetyError,safe_join,atomic_json,read_json,file_sha,redact
from .operations import digest

METRICS=('revenue','orders','adSpend','adRevenue','stock','uv','pv')

def number(value,*,positive=False):
 try:d=Decimal(str(value))
 except (InvalidOperation,ValueError):raise SafetyError('invalid-numeric-value') from None
 if not d.is_finite() or (positive and d<=0):raise SafetyError('invalid-numeric-value')
 return d

def decimal_text(value):return format(value,'f').rstrip('0').rstrip('.') if '.' in format(value,'f') else format(value,'f')

def read_rows(source,sheet=None):
 source=Path(source)
 if source.stat().st_size>64*1024*1024:raise SafetyError('input-too-large')
 if source.suffix.lower()=='.json':
  data=read_json(source);rows=data.get('rows',data.get('products')) if isinstance(data,dict) else data
 elif source.suffix.lower()=='.csv':
  raw=source.read_bytes()
  try:text=raw.decode('utf-8-sig')
  except UnicodeDecodeError:text=raw.decode('gb18030')
  rows=list(csv.DictReader(text.splitlines()))
 elif source.suffix.lower()=='.xlsx':
  # Mature parser optional; the Agent installs this public Python dependency, not another Skill repository.
  try:from openpyxl import load_workbook
  except ImportError:raise SafetyError('xlsx-needs-openpyxl-agent-install-public-dependency') from None
  book=load_workbook(source,read_only=True,data_only=True)
  try:
   visible=[s for s in book.worksheets if s.sheet_state=='visible']
   if sheet:ws=book[sheet]
   elif len(visible)==1:ws=visible[0]
   else:raise SafetyError('xlsx-select-source-sheet')
   iterator=ws.iter_rows(values_only=True);header=next(iterator,());keys=[str(v or '').strip() for v in header]
   if not keys or len(keys)!=len(set(keys)) or any(not k for k in keys):raise SafetyError('xlsx-invalid-header')
   rows=[dict(zip(keys,row)) for row in iterator if any(v is not None for v in row)]
  finally:book.close()
 else:raise SafetyError('source-must-be-json-csv-or-xlsx')
 if not isinstance(rows,list) or not rows or len(rows)>100000 or any(not isinstance(r,dict) for r in rows):raise SafetyError('invalid-or-empty-source-rows')
 return rows

def diagnose_rows(rows):
 if not rows or any(not isinstance(r,dict) for r in rows):raise SafetyError('source-rows-required')
 metrics={};missing=[];issues=[]
 for key in METRICS:
  values=[number(r[key]) for r in rows if r.get(key) not in ('',None)]
  status='complete' if len(values)==len(rows) else 'partial' if values else 'unavailable'
  metrics[key]={'status':status,'value':decimal_text(sum(values,Decimal(0))) if values else None,'includedRows':len(values),'totalRows':len(rows)}
  if status!='complete':missing.append(key)
 for index,row in enumerate(rows):
  ident=str(row.get('skuId',row.get('merchantCode',index+1)))
  for field,kind in (('stock','zero-stock'),('orders','zero-sales-in-uploaded-period')):
   if row.get(field) not in ('',None) and number(row[field])==0:issues.append({'row':index+1,'product':ident,'kind':kind,'action':'prepare-check-only-not-auto-modify'})
 derived={}
 for name,numerator,denominator in (('advertisingROAS','adRevenue','adSpend'),('revenuePerOrder','revenue','orders')):
  n,d=metrics[numerator],metrics[denominator]
  if n['status']==d['status']=='complete' and number(d['value'])>0:derived[name]={'status':'complete','value':decimal_text(number(n['value'])/number(d['value']))}
  else:derived[name]={'status':'unavailable','value':None}
 return {'scope':'uploaded-rows','rowCount':len(rows),'metrics':metrics,'derived':derived,'missingFields':missing,'issues':issues,'notChecked':['shop-wide completeness','employee analytics','advertising platform permissions','profit without complete costs'],'platformWrites':0}

def _spec(value):
 if not isinstance(value,dict) or not value:raise SafetyError('structured-specifications-required')
 return {unicodedata.normalize('NFKC',str(k)).strip().casefold():unicodedata.normalize('NFKC',str(v)).strip().casefold() for k,v in sorted(value.items())}

def compare_exact_specs(rows,specs):
 target=_spec(specs);accepted=[];excluded=[]
 for i,row in enumerate(rows):
  if not row.get('skuId') or not row.get('specs') or _spec(row['specs'])!=target:excluded.append({'row':i+1,'reason':'not-exact-spec'});continue
  if row.get('evidence')!='native-sku-context' or row.get('handPrice') in ('',None):excluded.append({'row':i+1,'reason':'missing-native-price-evidence'});continue
  price=number(row['handPrice'],positive=True);accepted.append({**row,'handPrice':decimal_text(price)})
 accepted.sort(key=lambda r:(number(r['handPrice']),str(r['skuId'])))
 return {'scope':'supplied-exact-spec-evidence','specs':specs,'top10':accepted[:10],'matchedCount':len(accepted),'excludedCount':len(excluded),'excluded':excluded,'repricing':'requires-separate-shop-plan-and-approval'}

def prepare_listing(product,source_root,output):
 from .product_schema import _validate_logical_properties
 _validate_logical_properties(product)
 if redact(product)!=product:raise SafetyError("credentials-not-allowed-in-listing-data")
 if not isinstance(product,dict) or not product.get('title') or not product.get('categoryId'):raise SafetyError('title-and-actual-category-required')
 skus=product.get('skus',[]);images=product.get('images',[])
 if not skus or not images:raise SafetyError('complete-skus-and-real-photos-required')
 identifiers=[]
 for sku in skus:
  ident=str(sku.get('merchantCode',''))
  if not ident or not isinstance(sku.get('specs'),dict):raise SafetyError('actual-merchant-code-and-specs-required')
  number(sku.get('price'),positive=True)
  stock=number(sku.get('stock'))
  if stock<0 or stock!=stock.to_integral_value():raise SafetyError('nonnegative-integer-stock-required')
  identifiers.append(ident)
 if len(identifiers)!=len(set(identifiers)):raise SafetyError('duplicate-sku-merchant-code')
 source_root=Path(source_root).resolve();output=Path(output).resolve()
 if output.exists() and any(output.iterdir()):raise SafetyError('listing-output-not-empty')
 refs=[]
 for image in images:
  p=safe_join(source_root,image)
  if not p.is_file() or p.suffix.lower() not in ('.jpg','.jpeg','.png','.webp'):raise SafetyError('trusted-source-image-required')
  refs.append((p,file_sha(p)))
 output.mkdir(parents=True,exist_ok=True);(output/'images').mkdir(exist_ok=True)
 photos=[]
 for i,(p,sha) in enumerate(refs):
  relative='images/'+str(i+1).zfill(2)+'-'+sha[:12]+p.suffix.lower();shutil.copyfile(p,safe_join(output,relative));photos.append({'localPath':relative,'sha256':sha,'source':'user-supplied','visualReview':'pending'})
 manifest={'merchantPackageSchemaVersion':1,'sourceProduct':product,'title':product['title'],'categoryId':str(product['categoryId']),'skus':skus,'sellingPoints':product.get('sellingPoints',[]),'source':{'kind':'local-photos','fingerprint':digest({'product':product,'photoHashes':[sha for _,sha in refs]})},'images':photos,'publication':{'intentId':uuid.uuid4().hex,'status':'not_submitted','needsCategorySchemaValidation':True},'video':None,'generation':{'status':'awaiting-provider','paidCalls':0}}
 if product.get('jdUrl'):manifest['jdUrl']=product['jdUrl']
 atomic_json(output/'manifest.json',manifest);return manifest

def material_audit(rows):
 slots=('white','transparent','scene1','scene2','sellingPoint','shortTitle');groups={};ids=[]
 for row in rows:
  spu,sku=str(row.get('spuId','')),str(row.get('skuId',''))
  if not spu or not sku:raise SafetyError('spu-and-all-sku-identifiers-required')
  if sku in ids:raise SafetyError('duplicate-sku-source')
  ids.append(sku);groups.setdefault(spu,[]).append(row)
 entries=[]
 for spu,skus in groups.items():entries.append({'spuId':spu,'skuIds':[str(s['skuId']) for s in skus],'missingBySku':{str(s['skuId']):[slot for slot in slots if not s.get(slot)] for s in skus}})
 batches=[{'spuCount':len(entries[i:i+199]),'products':entries[i:i+199]} for i in range(0,len(entries),199)]
 return {'spuCount':len(groups),'skuCount':len(ids),'batches':batches,'writes':0,'generation':'awaiting-provider-if-new-images-needed','next':'reuse-valid-existing-assets-or-prepare-host-copy; official-upload-only-after-approval'}

def _asset_download(url):
 parsed=urllib.parse.urlsplit(url);host=parsed.hostname or ''
 if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443) or not re.fullmatch(r'(?:img\d+|m|storage)\.360buyimg\.com',host):raise SafetyError('public-jd-cdn-asset-required')
 if parsed.query or parsed.fragment:raise SafetyError('signed-or-query-asset-needs-host-session-download')
 from .official import NoRedirect
 import socket,ipaddress
 for record in socket.getaddrinfo(host,443):
  if not ipaddress.ip_address(record[4][0]).is_global:raise SafetyError('private-asset-destination')
 try:
  with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(url,timeout=60) as response:raw=response.read(64*1024*1024+1)
 except Exception:raise SafetyError('asset-download-failed-no-auto-retry') from None
 if len(raw)>64*1024*1024:raise SafetyError('asset-too-large')
 return raw

def package_snapshot(snapshot,output,fetch=None):
 if redact(snapshot)!=snapshot:raise SafetyError("browser-credentials-not-allowed-in-snapshot")
 if not isinstance(snapshot,dict):raise SafetyError('snapshot-object-required')
 order=list(map(str,snapshot.get('skuOrder',[])));skus=snapshot.get('skus',[]);ids=[str(s.get('skuId','')) for s in skus]
 if not order or len(order)!=len(set(order)) or set(order)!=set(ids) or len(ids)!=len(set(ids)) or str(snapshot.get('selectedSkuId')) not in order:raise SafetyError('complete-native-sku-order-required')
 if not re.fullmatch(r'https://item\.jd\.com/\d+\.html',str(snapshot.get('url',''))):raise SafetyError('actual-canonical-jd-source-required')
 for sku in skus:
  if sku.get('priceEvidence')!='native-sku-context' or sku.get('handPrice') in ('',None):raise SafetyError('each-sku-needs-native-price-evidence')
  number(sku['handPrice'],positive=True)
 output=Path(output).resolve()
 if output.exists() and any(output.iterdir()):raise SafetyError('snapshot-output-not-empty')
 output.mkdir(parents=True,exist_ok=True);assets=[]
 for i,asset in enumerate(snapshot.get('assets',[])):
  url=asset.get('url','');raw=(fetch or _asset_download)(url)
  suffix=Path(urllib.parse.urlsplit(url).path).suffix.lower()
  if suffix not in ('.jpg','.jpeg','.png','.webp','.mp4'):raise SafetyError('unsupported-asset-format')
  name='assets/'+str(i+1).zfill(3)+'-'+hashlib.sha256(raw).hexdigest()[:12]+suffix;p=safe_join(output,name);p.parent.mkdir(exist_ok=True);p.write_bytes(raw)
  assets.append({'localPath':name,'sha256':file_sha(p),'kind':asset.get('kind','image'),'skuId':str(asset.get('skuId',''))})
 result={**snapshot,'assets':assets,'assetCount':len(assets),'scope':'observed-native-product-context','publication':'not-requested'}
 atomic_json(output/'product.json',result)
 with (output/'skus.csv').open('w',encoding='utf-8-sig',newline='') as stream:
  writer=csv.DictWriter(stream,fieldnames=['skuId','handPrice','priceEvidence']);writer.writeheader();writer.writerows({k:r.get(k,'') for k in writer.fieldnames} for r in sorted(skus,key=lambda s:order.index(str(s['skuId']))))
 return result

def attach_video(manifest_path,video,cover=None,review=None):
 manifest_path=Path(manifest_path).resolve();root=manifest_path.parent;manifest=read_json(manifest_path)
 if not isinstance(manifest,dict) or manifest.get('merchantPackageSchemaVersion')!=1:raise SafetyError('merchant-listing-manifest-required')
 video=Path(video).resolve()
 if not video.is_file() or b'ftyp' not in video.read_bytes()[:64]:raise SafetyError('existing-mp4-required')
 sha=file_sha(video);relative='video/'+sha[:16]+'.mp4';dest=safe_join(root,relative);dest.parent.mkdir(exist_ok=True)
 if video!=dest:shutil.copyfile(video,dest)
 info={'schemaVersion':1,'origin':'user-supplied','localPath':relative,'sha256':sha,'bindable':False,'taskId':None,'upstreamRepository':'ctzlyj/jd-pop-main-video-skill','review':{'technical':'not-verified','visual':'pending','voice':'pending'}}
 if cover:
  p=Path(cover).resolve();cover_sha=file_sha(p);name='video/'+cover_sha[:16]+p.suffix.lower();shutil.copyfile(p,safe_join(root,name));info.update(coverPath=name,coverSha256=cover_sha)
 if review:
  if review.get('sha256')!=sha:raise SafetyError('video-review-hash-mismatch')
  info['review']=review
  info['bindable']=all(review.get(k) is True for k in ('technicalPass','visualPass','voiceConfirmed')) and bool(info.get('coverSha256'))
 manifest['video']=info;atomic_json(manifest_path,manifest);return manifest
