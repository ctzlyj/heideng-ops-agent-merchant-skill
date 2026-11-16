"""Current-key text discovery and bounded validated concurrency. No credential persistence."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx

class TextPoolUnavailable(RuntimeError):
    """Unresolved text must be authored by the Agent, never fabricated/replayed."""

def text_candidates(rows):
    result=[]
    for item in rows:
        model=item.get('id')
        if not isinstance(model,str) or not model or model.strip()!=model:continue
        lowered=model.lower()
        if any(x in lowered for x in ('image','video','audio','realtime','embedding','rerank')):continue
        # Exclude documented non-text models, probe unknown future text families rather than
        # freezing a user's model authorization to today's developer account.
        if model in {'MiniMax-H3','Oxygen-Product-Pro','Oxygen-Imagen'}:continue
        modality=str(item.get('type') or item.get('modality') or '').lower()
        if modality and any(x in modality for x in ('image','video','audio','embedding')):continue
        if model not in result:result.append(model)
    return result

def parse_json(text):
    if not isinstance(text,str) or not text.strip():raise ValueError('No output text')
    stripped=text.strip()
    if '</think>' in stripped:stripped=stripped.rsplit('</think>',1)[1].strip()
    if stripped.startswith('```'):
        lines=stripped.splitlines();stripped='\n'.join(lines[1:-1]) if lines[-1].strip()=='```' else stripped
    value=json.loads(stripped)
    if not isinstance(value,dict):raise ValueError('Expected complete JSON object')
    return value

class TextPool:
    def __init__(self,key,*,base_url=None,timeout=40,concurrency=20,start_interval=.1,transport=None,cancelled=None):
        raise TextPoolUnavailable('external-text-provider-not-configured; no company model discovery or quota fallback')
    def close(self):self.http.close()
    def _start(self):
        with self.start_lock:
            now=time.monotonic();delay=self.next_start-now
            if delay>0:time.sleep(delay)
            self.next_start=time.monotonic()+self.interval
    def _check_cancelled(self):
        if self.cancelled():raise TextPoolUnavailable('Text pipeline cancelled before dispatch')
    def _healthy(self,model):
        self._check_cancelled()
        with self.lock:
            if model in self.disabled:raise TextPoolUnavailable('Text model disabled in current run')
            if self.cooldown.get(model,0)>time.monotonic():raise TextPoolUnavailable('Text model cooling down')
    def _call(self,model,system,user,probe=False):
        self._check_cancelled()
        with self.semaphore:
            with self.lock:
                if model in self.disabled:raise TextPoolUnavailable('This text model was disabled for the current run; no replay')
                if self.cooldown.get(model,0)>time.monotonic():raise TextPoolUnavailable('Text model is cooling down; use another current-key model')
            self._start();self._healthy(model);protocol='messages' if model.lower().startswith('claude-') else 'chat/completions'
            # Reasoning models need a complete final output;32-token probes incorrectly
            # classify an authorized model as unusable when thinking consumes the budget.
            if protocol=='messages':
                payload={'model':model,'system':system,'messages':[{'role':'user','content':user}],'max_tokens':256 if probe else 8192}
                response=self.http.post('/messages',json=payload,headers={'anthropic-version':'2023-06-01'},timeout=min(self.timeout,12) if probe else self.timeout)
            else:
                payload={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],'max_tokens':512 if probe else 8192,'stream':False,'thinking':{'type':'disabled'}}
                response=self.http.post('/chat/completions',json=payload,timeout=min(self.timeout,12) if probe else self.timeout)
            if response.status_code>=400:
                try:value=response.json();code=str((value.get('error') or {}).get('code',''))
                except Exception:code=''
                if response.status_code in (401,403) or code=='2007' or any(word in str(value if 'value' in locals() else '').lower() for word in ('未授权','授权失败','permission denied','not authorized')):
                    with self.lock:self.disabled.add(model)
                if response.status_code==429 and code!='2007':
                    try:delay=float(response.headers.get('retry-after','2'))
                    except ValueError:delay=2
                    with self.lock:self.cooldown[model]=time.monotonic()+min(60,max(1,delay))
                raise TextPoolUnavailable('Text model request rejected: HTTP%d code%s' % (response.status_code,code))
            value=response.json()
            if protocol=='messages':
                if value.get('stop_reason')=='max_tokens':raise ValueError('Truncated text output')
                text=''.join(x.get('text','') for x in value.get('content',[]) if isinstance(x,dict) and x.get('type')=='text')
            else:
                choices=value.get('choices') or []
                if not choices:raise ValueError('No text choices')
                if choices[0].get('finish_reason') not in ('stop',None):raise ValueError('Incomplete text output')
                text=(choices[0].get('message') or {}).get('content')
            return parse_json(text)
    def discover(self):
        with self.discover_lock:
            self._check_cancelled()
            if self.active is not None:
                self._refresh_transient()
                return list(self.active)
            start=time.perf_counter()
            try:
                self._check_cancelled()
                response=self.http.get('/models');response.raise_for_status();value=response.json()
                candidates=text_candidates(value.get('data',[]))
            except Exception:
                self.active=[];raise TextPoolUnavailable('Current-key model catalog unavailable; Agent fallback required') from None
            def probe(model):
                started=time.perf_counter()
                try:
                    value=self._call(model,'输出严格JSON，不要推理解释。','仅输出 {"ok":true}',probe=True)
                    if value!={'ok':True}:raise ValueError('Probe not completed')
                    return {'model':model,'usable':True,'seconds':round(time.perf_counter()-started,3)}
                except Exception as e:return {'model':model,'usable':False,'seconds':round(time.perf_counter()-started,3),'failureClass':type(e).__name__,'transient':model in self.cooldown and model not in self.disabled}
            by_model={}
            with ThreadPoolExecutor(max_workers=self.limit) as pool:
                for future in as_completed([pool.submit(probe,model) for model in candidates]):
                    record=future.result();by_model[record['model']]=record
            self.probes=[by_model[model] for model in candidates];self.active=[model for model in candidates if by_model[model]['usable']]
            self.transient={m for m in candidates if by_model[m].get('transient')}
            self.discover_seconds=round(time.perf_counter()-start,3)
            if not self.active:raise TextPoolUnavailable('No validated text model available for current key; Agent fallback required')
            return list(self.active)
    def _refresh_transient(self):
        # Bounded re-probe after documented429cooldown; reuse this key's catalog,
        # never make a known authorization/quota failure eligible again.
        due=[m for m in self.transient if m not in self.disabled and self.cooldown.get(m,0)<=time.monotonic() and self.refresh_counts.get(m,0)<2]
        for model in due:
            self._check_cancelled();self.refresh_counts[model]=self.refresh_counts.get(model,0)+1
            try:
                value=self._call(model,'输出严格JSON，不要推理解释。','仅输出 {"ok":true}',probe=True)
                if value!={'ok':True}:raise ValueError('Invalid refresh probe')
                if model not in self.active:self.active.append(model)
                self.transient.discard(model)
            except Exception:
                pass

    def generate(self,system,user,validator):
        models=self.discover()
        with self.lock:
            viable=[m for m in models if m not in self.disabled and self.cooldown.get(m,0)<=time.monotonic()]
            if not viable:raise TextPoolUnavailable('Text models unavailable/cooling down; Agent fallback required')
            first=self.cursor%len(viable);self.cursor+=1
            candidates=viable[first:]+viable[:first]
        # At most3 validated attempts per unit of text. Do not fan out identical paid
        # prompts to every model, or accept speculative/invalid text to look faster.
        for model in candidates[:3]:
            started=time.perf_counter()
            try:
                value=self._call(model,system,user);result=validator(value)
                with self.lock:
                    self.usage[model]=self.usage.get(model,0)+1;self.elapsed[model]=round(self.elapsed.get(model,0)+time.perf_counter()-started,3)
                return result
            except Exception:
                with self.lock:self.failures[model]=self.failures.get(model,0)+1
        raise TextPoolUnavailable('Three models failed text validation/availability; Agent fills only unresolved frozen SKU/SPU text')
    def stats(self):
        with self.lock:return {'catalogProbes':list(self.probes),'usableModels':list(self.active or []),'disabledModels':sorted(self.disabled),'usage':dict(self.usage),'failures':dict(self.failures),'requestSeconds':dict(self.elapsed),'discoverySeconds':self.discover_seconds,'maxConcurrentRequests':self.limit,'keyLogged':False}
