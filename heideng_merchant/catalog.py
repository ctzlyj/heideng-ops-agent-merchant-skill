"""Capability discovery, not an execution whitelist."""
from pathlib import Path
from .safety import read_json

def load_catalog():return read_json(Path(__file__).resolve().parents[1]/'registry.json')

def route(request):
 catalog=load_catalog();text=str(request).casefold();matches=[]
 for c in catalog['capabilities']:
  score=sum(len(t) for t in c['triggers'] if t.casefold() in text)
  if score:matches.append({**c,'score':score})
 matches.sort(key=lambda c:-c['score'])
 return {'status':'matched' if matches else 'open-toolbox','request':request,'matches':matches,'rule':'用户描述目标，Agent可组合目录外合法工具；费用、店铺权限和内部资源隔离不能绕过'}
