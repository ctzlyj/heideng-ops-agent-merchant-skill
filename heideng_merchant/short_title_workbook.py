"""Bounded native-template XLSX compilation; never proves origin or import."""
import io,zipfile,re,stat,copy,xml.etree.ElementTree as ET
from .safety import SafetyError,redact
from .products import identifier
from .short_title_contract import title_checked,BATCH
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
ET.register_namespace('',NS)
MAX_BYTES=5*1024*1024

def _parts(raw):
 if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_BYTES:raise SafetyError('bounded-short-title-template-required')
 try:
  with zipfile.ZipFile(io.BytesIO(raw)) as z:
   infos=z.infolist();names=[i.filename for i in infos]
   if len(infos)>256 or len(names)!=len(set(names)) or sum(i.file_size for i in infos)>32*1024*1024:raise SafetyError('bounded-unique-short-title-template-parts-required')
   parts={}
   for info in infos:
    name=info.filename
    if info.is_dir():
     if not re.fullmatch(r'[A-Za-z0-9_./\[\]-]+',name.rstrip('/')) or name.startswith('/') or any(p in ('','..','.') for p in name.rstrip('/').split('/')) or stat.S_ISLNK(info.external_attr>>16) or info.file_size!=0:raise SafetyError('safe-empty-short-title-template-directories-required')
     parts[name]=b'';continue
    if not re.fullmatch(r'[A-Za-z0-9_./\[\]-]+',name) or name.startswith('/') or any(p in ('','..','.') for p in name.split('/')) or stat.S_ISLNK(info.external_attr>>16) or info.flag_bits&1 or info.file_size>8*1024*1024 or not name.endswith(('.xml','.rels')) or 'vba' in name.lower():raise SafetyError('safe-xml-only-short-title-template-required')
    body=z.read(info)
    try:text=body.decode('utf-8-sig')
    except UnicodeDecodeError:raise SafetyError('utf8-short-title-template-required') from None
    if re.search(r'<!DOCTYPE|<!ENTITY',text,re.I) or redact(text)!=text or re.search(r'(?i)(?<![A-Z0-9])[A-Z]:[\\/]|/Users/|/home/',text):raise SafetyError('private-or-active-short-title-template-refused')
    root=ET.fromstring(body)
    if any(e.tag.endswith('}f') or e.tag=='f' for e in root.iter()):raise SafetyError('short-title-template-formulas-refused')
    if name.endswith('.rels') and any(e.attrib.get('TargetMode')=='External' for e in root.iter()):raise SafetyError('short-title-template-external-relationships-refused')
    if 'macroEnabled' in text:raise SafetyError('short-title-template-macros-refused')
    from .short_title_workbook_graph import namespaces
    namespaces(body)
    parts[name]=body
   if not {'[Content_Types].xml','xl/workbook.xml','xl/worksheets/sheet1.xml'}<=set(parts) or [n for n in names if re.fullmatch(r'xl/worksheets/[^/]+\.xml',n)]!=['xl/worksheets/sheet1.xml']:raise SafetyError('single-known-short-title-sheet-required')
   from .short_title_workbook_graph import check_graph
   check_graph(parts)
   return infos,parts
 except SafetyError:raise
 except (zipfile.BadZipFile,ET.ParseError,RuntimeError,KeyError,OSError):raise SafetyError('invalid-short-title-template') from None

def _strings(parts):
 if 'xl/sharedStrings.xml' not in parts:return []
 root=ET.fromstring(parts['xl/sharedStrings.xml'])
 return [''.join(e.itertext()) for e in root.findall('{'+NS+'}si')]

def _value(cell,strings):
 if cell is None:return None
 if cell.attrib.get('t')=='s':
  v=cell.find('{'+NS+'}v')
  try:return strings[int(v.text)]
  except (IndexError,ValueError,TypeError,AttributeError):raise SafetyError('valid-short-title-header-string-reference-required') from None
 if cell.attrib.get('t')=='inlineStr':return ''.join(cell.find('{'+NS+'}is').itertext())
 return cell.findtext('{'+NS+'}v')

def compile_template(template,rows):
 if not isinstance(rows,list) or not rows or len(rows)>BATCH:raise SafetyError('short-title-workbook-one-to-5000-rows-required')
 clean=[];seen=set()
 for row in rows:
  if not isinstance(row,dict) or set(row)!={'skuId','shortTitle'}:raise SafetyError('short-title-workbook-exact-columns-required')
  sku=identifier(row['skuId']);text=title_checked(row['shortTitle'])
  if sku in seen:raise SafetyError('unique-short-title-workbook-sku-required')
  seen.add(sku);clean.append((sku,text))
 infos,parts=_parts(template);original=parts['xl/worksheets/sheet1.xml'].decode('utf-8-sig');sheet=ET.fromstring(original);data=sheet.find('{'+NS+'}sheetData');strings=_strings(parts)
 if data is None:raise SafetyError('short-title-template-sheetData-required')
 if any(e.tag!='{'+NS+'}row' for e in data) or len([r for r in data if r.attrib.get('r')=='1'])!=1 or len([r for r in data if r.attrib.get('r')=='2'])!=1:raise SafetyError('unique-short-title-template-header-rows-required')
 header=next(r for r in data if r.attrib['r']=='2');cells={c.attrib.get('r'):c for c in header}
 if len(cells)!=len(header) or _value(cells.get('A2'),strings)!='SKUID' or _value(cells.get('B2'),strings)!='短标题':raise SafetyError('actual-short-title-template-headers-required')
 for row in list(data):
  try:number=int(row.attrib['r'])
  except (KeyError,ValueError):raise SafetyError('numbered-short-title-template-rows-required') from None
  if number<1:raise SafetyError('numbered-short-title-template-rows-required')
  if number>=3:data.remove(row)
 # Clear unreferenced sample strings, retaining all header text and native formatting.
 used=set()
 for row in data:
  for cell in row:
   if cell.attrib.get('t')=='s':
    value=cell.find('{'+NS+'}v')
    try:index=int(value.text);strings[index]
    except (ValueError,TypeError,IndexError,AttributeError):raise SafetyError('valid-short-title-header-string-reference-required') from None
    used.add(index)
 if 'xl/sharedStrings.xml' in parts:
  old=ET.fromstring(parts['xl/sharedStrings.xml']);items=old.findall('{'+NS+'}si');mapping={old_index:new_index for new_index,old_index in enumerate(sorted(used))}
  for item in list(old):old.remove(item)
  for index in sorted(used):old.append(items[index])
  old.set('count',str(len(used)));old.set('uniqueCount',str(len(used)));from .short_title_workbook_graph import serialize_preserving
  parts['xl/sharedStrings.xml']=serialize_preserving(old,parts['xl/sharedStrings.xml'])
  for row in data:
   for cell in row:
    if cell.attrib.get('t')=='s':cell.find('{'+NS+'}v').text=str(mapping[int(cell.find('{'+NS+'}v').text)])
 for number,(sku,title) in enumerate(clean,3):
  row=ET.SubElement(data,'{'+NS+'}row',{'r':str(number)})
  for column,value in (('A',sku),('B',title)):
   cell=ET.SubElement(row,'{'+NS+'}c',{'r':column+str(number),'t':'inlineStr'});text=ET.SubElement(ET.SubElement(cell,'{'+NS+'}is'),'{'+NS+'}t');text.text=value;text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
 replacement=ET.tostring(data,encoding='unicode');updated,count=re.subn(r'<(?:[A-Za-z_][\w.-]*:)?sheetData\b[^>]*>.*?</(?:[A-Za-z_][\w.-]*:)?sheetData>',lambda m:replacement,original,flags=re.S)
 if count!=1:raise SafetyError('unique-short-title-template-sheetData-required')
 updated,count=re.subn(r'<((?:[A-Za-z_][\w.-]*:)?dimension)\b[^>]*/>',lambda m:'<'+m.group(1)+' ref="A1:B'+str(len(clean)+2)+'"/>',updated)
 if count!=1:raise SafetyError('unique-short-title-template-dimension-required')
 parts['xl/worksheets/sheet1.xml']=updated.encode('utf-8');out=io.BytesIO()
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for info in infos:z.writestr(info,parts[info.filename])
 result=out.getvalue()
 if len(result)>MAX_BYTES:raise SafetyError('short-title-workbook-exceeds-platform-size')
 return result
