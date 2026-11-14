"""Keep binary media payloads out of public command output, including JSON text."""
import base64,hashlib,json

def public_result(value):
 media=set()
 def parsed(text):
  if isinstance(text,str) and text.lstrip().startswith(('{','[')):
   try:return json.loads(text)
   except (ValueError,TypeError,RecursionError):pass
  return None
 def collect(node):
  if isinstance(node,dict):
   for key,child in node.items():
    if key=='imgBase64' and isinstance(child,str):media.add(child)
    else:collect(child)
  elif isinstance(node,(list,tuple)):
   for child in node:collect(child)
  elif isinstance(node,str):
   decoded=parsed(node)
   if decoded is not None:collect(decoded)
 def text(node):
  for encoded in media:
   if encoded and len(encoded)<=len(node):node=node.replace(encoded,'[ENCODED MEDIA OMITTED]')
  return node
 def clean(node):
  if isinstance(node,dict):
   result={}
   for key,child in node.items():
    visible_key=text(key) if isinstance(key,str) else key
    if key=='imgBase64' and isinstance(child,str):
     try:sha=hashlib.sha256(base64.b64decode(child,validate=True)).hexdigest()
     except (ValueError,TypeError):sha=None
     result[visible_key]={'omitted':True,'encodedBytes':len(child),'originalSha256':sha,'location':'local task state only'}
    else:result[visible_key]=clean(child)
   return result
  if isinstance(node,(list,tuple)):return [clean(child) for child in node]
  if isinstance(node,str):
   decoded=parsed(node)
   if decoded is not None:
    filtered=clean(decoded)
    if filtered!=decoded:return json.dumps(filtered,ensure_ascii=False,separators=(',',':'))
   return text(node)
  return node
 collect(value);return clean(value)
