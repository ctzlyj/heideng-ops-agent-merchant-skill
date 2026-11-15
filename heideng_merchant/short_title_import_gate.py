"""Native import evidence blocks code switching until C proves final verification."""
import re
from pathlib import Path
from . import VERSION
from .safety import SafetyError,safe_join,read_json
from .short_title_import_state import record,evidence

ID=re.compile('[a-f0-9]{24}')
FOLDERS=('short-title-import-attempts','short-title-import-dispatches','short-title-import-acks','short-title-import-observations','short-title-import-anchors')
def entries(state,relative):
 root=safe_join(state,relative)
 if not root.exists():return []
 if not root.is_dir():raise SafetyError('unreviewed-native-title-import-layout')
 return [safe_join(state,relative+'/'+p.name) for p in root.iterdir()]
def busy(state):
 state=Path(state).absolute();roots={};expected_files=set();intents=set()
 for p in entries(state,'short-title-imports'):
  if p.is_file() and p.suffix=='.lock' and ID.fullmatch(p.stem):continue
  if not p.is_file() or p.suffix!='.json' or not ID.fullmatch(p.stem):return True
  root=record(state,None,p.stem);roots[p.stem]=root;intents.add(root['scope']['intentHash'][:24]);ev=evidence(state,root);from .short_title_result_state import read_log;read_log(state,root,ev[3])
  from .short_title_effect_state import read_log as effect_log
  effect_count=effect_log(state,root,ev[3])[1]
  if effect_count or root['scope']['runtimeVersion']!=VERSION or ev[1] or ev[2] or ev[3] or ev[4] or ev[5]:return True
  expected_files.update(row['localPath'] for row in root['scope']['artifacts'])
 for folder in ('short-title-import-approvals',*FOLDERS):
  for directory in entries(state,folder):
   if not directory.is_dir() or directory.name not in roots:return True
   if folder in FOLDERS and entries(state,folder+'/'+directory.name):return True
 for folder in ('short-title-result-observations','short-title-result-receipts','short-title-effect-observations','short-title-effect-receipts'):
  for directory in entries(state,folder):
   if not directory.is_dir() or directory.name not in roots:return True
 for folder in ('short-title-result-heads','short-title-effect-heads'):
  for p in entries(state,folder):
   if not p.is_file() or p.suffix!='.json' or p.stem not in roots:return True
 for p in entries(state,'short-title-import-intents'):
  if not p.is_file() or p.suffix!='.json' or p.stem not in intents:return True
  value=read_json(p)
  if not isinstance(value,dict) or value.get('importId') not in roots:return True
 actual=set()
 for directory in entries(state,'short-title-import-workbooks'):
  if not directory.is_dir() or not ID.fullmatch(directory.name):return True
  files=entries(state,'short-title-import-workbooks/'+directory.name)
  if not files:return True
  for p in files:
   if not p.is_file() or p.suffix!='.xlsx':return True
   actual.add('short-title-import-workbooks/'+directory.name+'/'+p.name)
 return actual!=expected_files
