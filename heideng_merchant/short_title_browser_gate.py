"""Fail-closed browser/source eligibility; never opens a browser or reads its cookies."""
from pathlib import Path
from .safety import SafetyError,safe_join,read_json
from .state import FileLock
from .short_title_browser import _source_record,_owner
from .short_titles import ShortTitlePlans
import re

ID=re.compile('[a-f0-9]{24}')

def _entries(state,relative):
 root=safe_join(state,relative)
 if not root.exists():return []
 if not root.is_dir():raise SafetyError('unreviewed-short-title-browser-state-layout')
 return [safe_join(state,relative+'/'+p.name) for p in root.iterdir()]

def busy(state):
 state=Path(state).absolute();sessions={};plans=ShortTitlePlans(state,None)
 for root in _entries(state,'browser/short-title'):
  if not root.is_dir() or not ID.fullmatch(root.name):return True
  owner=read_json(safe_join(state,'browser/short-title/'+root.name+'/owner.json'))
  if not isinstance(owner,dict) or not isinstance(owner.get('planId'),str):return True
  plan=plans.plan(owner['planId'])
  if owner!=_owner(state,root.name,plan):return True
  entries={p.name:p for p in _entries(state,'browser/short-title/'+root.name)}
  if set(entries)!={'owner.json','lifecycle.json','owner.lock','context-data'} or any(not entries[n].is_file() for n in ('owner.json','lifecycle.json','owner.lock')) or not entries['context-data'].is_dir() or entries['owner.lock'].stat().st_size<1:return True
  lifecycle=read_json(entries['lifecycle.json'])
  if lifecycle!={'sessionId':root.name,'status':'closed'}:return True
  try:
   with FileLock(entries['owner.lock'],timeout=0):pass
  except SafetyError:return True
  sessions[root.name]=owner
 records={}
 for relative,suffix in (('short-title-browser-sources','.json'),('short-title-browser-observations','.json'),('short-title-browser-templates','.xlsx')):
  ids=set()
  for p in _entries(state,relative):
   if not p.is_file() or p.suffix!=suffix or not ID.fullmatch(p.stem) or p.stem not in sessions:return True
   ids.add(p.stem)
  records[relative]=ids
 ids=records['short-title-browser-sources']
 if any(group!=ids for group in records.values()):return True
 for source_id in ids:_source_record(state,None,source_id)
 return False
