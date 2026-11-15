"""Supported flat XLSX package graph and lexical namespace preservation."""
import posixpath,re,io,html,urllib.parse,xml.etree.ElementTree as ET
from .safety import SafetyError
MAIN='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
OFFICE='http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
CT='http://schemas.openxmlformats.org/package/2006/content-types'
MC='http://schemas.openxmlformats.org/markup-compatibility/2006'
PART=re.compile(r'(?:\[Content_Types\]\.xml|_rels/\.rels|docProps/(?:app|core|custom)\.xml|xl/(?:workbook|styles|sharedStrings)\.xml|xl/_rels/workbook\.xml\.rels|xl/theme/theme[0-9]+\.xml|xl/worksheets/sheet1\.xml|xl/worksheets/_rels/sheet1\.xml\.rels)')

def resolve(base,target):
 if not isinstance(target,str) or not target or '\\' in target or '%' in target or any(ord(c)<32 for c in target):raise SafetyError('safe-internal-template-target-required')
 p=urllib.parse.urlsplit(target)
 if p.scheme or p.netloc or p.query or p.fragment:raise SafetyError('template-external-target-refused')
 path=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(base),target))
 if path.startswith('../') or path in ('','..','.') or path.startswith('/'):raise SafetyError('template-target-outside-package')
 return path

def check_graph(parts):
 for name in parts:
  if name.endswith('/'):continue
  if not PART.fullmatch(name):raise SafetyError('unsupported-active-or-unknown-template-part')
 roots={'xl/worksheets/sheet1.xml':'{'+MAIN+'}worksheet','xl/sharedStrings.xml':'{'+MAIN+'}sst','xl/styles.xml':'{'+MAIN+'}styleSheet','docProps/core.xml':'{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}coreProperties','docProps/app.xml':'{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Properties','docProps/custom.xml':'{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}Properties'}
 active={'connections','connection','webPr','queryTable','externalReference','externalReferences','externalBook','oleObject','oleObjects','ddeLink','oleLink','webPublishItems','webPublishing'}
 for name,raw in parts.items():
  if name.endswith('/'):continue
  root=ET.fromstring(raw)
  if name in roots and root.tag!=roots[name]:raise SafetyError('correct-native-template-part-root-required')
  if any(element.tag.split('}')[-1] in active for element in root.iter()):raise SafetyError('active-external-template-element-refused')
 types=ET.fromstring(parts['[Content_Types].xml'])
 if types.tag!='{'+CT+'}Types':raise SafetyError('native-template-content-types-required')
 defaults={};overrides={}
 for entry in types:
  if entry.tag=='{'+CT+'}Default':
   key=entry.get('Extension');mime=entry.get('ContentType');dest=defaults
  elif entry.tag=='{'+CT+'}Override':
   part=entry.get('PartName')
   if not isinstance(part,str) or not part.startswith('/'):raise SafetyError('valid-template-content-type-part-required')
   key=resolve('',part);mime=entry.get('ContentType');dest=overrides
   if key not in parts:raise SafetyError('template-content-type-target-missing')
  else:raise SafetyError('known-template-content-type-entry-required')
  if not isinstance(key,str) or not isinstance(mime,str) or key in dest:raise SafetyError('unique-template-content-types-required')
  dest[key]=mime
 expected={'xl/workbook.xml':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml','xl/worksheets/sheet1.xml':'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml','xl/sharedStrings.xml':'application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml'}
 for name,mime in expected.items():
  if name in parts and overrides.get(name,defaults.get(name.rsplit('.',1)[-1]))!=mime:raise SafetyError('correct-template-workbook-content-type-required')
 relationships={}
 allowed={OFFICE+role for role in ('officeDocument','worksheet','styles','sharedStrings','theme','extended-properties','custom-properties')}|{REL+'/metadata/core-properties'}
 for name,raw in parts.items():
  if not name.endswith('.rels'):continue
  root=ET.fromstring(raw)
  if root.tag!='{'+REL+'}Relationships':raise SafetyError('native-template-relationships-required')
  base='' if name=='_rels/.rels' else name.replace('/_rels/','/').removesuffix('.rels');edges={}
  for edge in root:
   eid=edge.get('Id');kind=edge.get('Type')
   if edge.tag!='{'+REL+'}Relationship' or not isinstance(eid,str) or eid in edges or kind not in allowed or edge.get('TargetMode') not in (None,'Internal'):raise SafetyError('known-unique-internal-template-relationship-required')
   target=resolve(base,edge.get('Target'))
   if target not in parts or target.endswith('/'):raise SafetyError('template-relationship-target-missing')
   edges[eid]=(kind,target)
  relationships[name]=edges
 root_edges=relationships.get('_rels/.rels',{})
 if [target for kind,target in root_edges.values() if kind==OFFICE+'officeDocument']!=['xl/workbook.xml']:raise SafetyError('one-bound-template-workbook-required')
 book=ET.fromstring(parts['xl/workbook.xml']);sheets=book.find('{'+MAIN+'}sheets')
 if book.tag!='{'+MAIN+'}workbook' or sheets is None or len(sheets)!=1 or sheets[0].tag!='{'+MAIN+'}sheet':raise SafetyError('one-declared-template-worksheet-required')
 rid=sheets[0].get('{'+OFFICE.removesuffix('/')+'}id');edges=relationships.get('xl/_rels/workbook.xml.rels',{})
 if edges.get(rid)!=(OFFICE+'worksheet','xl/worksheets/sheet1.xml') or sum(kind==OFFICE+'worksheet' for kind,target in edges.values())!=1:raise SafetyError('declared-template-sheet-must-bind-rewritten-part')

def namespaces(raw):
 bindings={'xml':'http://www.w3.org/XML/1998/namespace'}
 try:
  for event,(prefix,uri) in ET.iterparse(io.BytesIO(raw),events=('start-ns',)):
   if prefix and prefix in bindings and bindings[prefix]!=uri:raise SafetyError('template-namespace-shadowing-needs-reviewed-adapter')
   if prefix not in bindings:bindings[prefix]=uri
  root=ET.fromstring(raw)
 except ET.ParseError:raise SafetyError('valid-template-namespace-document-required') from None
 for element in root.iter():
  for key,value in element.attrib.items():
   if key in {'{'+MC+'}Ignorable','{'+MC+'}ProcessContent','{'+MC+'}PreserveElements','{'+MC+'}PreserveAttributes'} or (element.tag=='{'+MC+'}Choice' and key=='Requires'):
    for token in value.split():
     prefix=token.split(':',1)[0]
     if prefix not in bindings:raise SafetyError('bound-template-compatibility-prefix-required')
 return bindings

def serialize_preserving(element,original):
 bindings=namespaces(original)
 for prefix,uri in bindings.items():
  if prefix=='xml' or re.fullmatch(r'ns[0-9]+',prefix):continue
  ET.register_namespace(prefix,uri)
 raw=ET.tostring(element,encoding='utf-8');existing=dict((prefix,uri) for event,(prefix,uri) in ET.iterparse(io.BytesIO(raw),events=('start-ns',)))
 extra=[]
 for prefix,uri in bindings.items():
  if prefix=='xml' or prefix in existing:continue
  attr='xmlns'+(':'+prefix if prefix else '')
  extra.append(' '+attr+'="'+html.escape(uri,quote=True)+'"')
 if extra:
  end=raw.index(b'>');pos=end-1 if raw[end-1:end]==b'/' else end;raw=raw[:pos]+''.join(extra).encode('utf-8')+raw[pos:]
 namespaces(raw)
 return raw
