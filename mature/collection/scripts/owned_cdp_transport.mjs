/** Browser plumbing only. Original collector retains signatures, SKU/price rules and receipts. */
import fs from 'node:fs';
import path from 'node:path';
import cdpModule from '../../diagnosis/scripts/cdp-lib.js';
const {Cdp}=cdpModule;
let context=null, client=null, connecting=null;
const owned=new Set(), sessions=new Map(), captures=new Map();
function validateContext(c,endpoint=c?.cdpEndpoint){
 if(!c||c.owned!==true||!(c.isolated===true||c.verifiedReuse===true)||!c.contextId||!c.session)throw Error('COLLECTION_OWNED_BROWSER_REQUIRED');
 let u;try{u=new URL(endpoint);}catch{throw Error('COLLECTION_CDP_ENDPOINT_REQUIRED');}
 if(u.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(u.hostname)||!u.port||u.username||u.password||u.search||u.hash)throw Error('COLLECTION_CDP_ENDPOINT_REQUIRED');
 if(c.isolated===true){
  let home,profile;try{home=fs.realpathSync(process.env.HEIDENG_MERCHANT_HOME);profile=fs.realpathSync(c.profileDir);}catch{throw Error('COLLECTION_OWNED_BROWSER_REQUIRED');}
  const rel=path.relative(path.join(home,'browser-profiles'),profile);if(!rel||rel.startsWith('..')||path.isAbsolute(rel))throw Error('COLLECTION_OWNED_BROWSER_REQUIRED');
 }
 return c;
}
export async function configure(c){context=validateContext(c);}
async function connection(){
 if(!context)throw Error('COLLECTION_OWNED_BROWSER_REQUIRED');
 if(!client){connecting ||= Cdp.connect(context.cdpEndpoint, endpoint=>validateContext(context,endpoint));client=await connecting;}
 return client;
}
async function sessionFor(tab){
 if(!tab||(!owned.has(tab)&&tab!==context?.tab))throw Error('TASK_TAB_NOT_OWNED');
 if(!sessions.has(tab))sessions.set(tab,await (await connection()).attach(tab));
 return sessions.get(tab);
}
export class Page{
 constructor(session,idleTimeout,_tab,windowMode){if(!context||session!==context.session||windowMode!=='background')throw Error('COLLECTION_OWNED_BROWSER_REQUIRED');this.tab=_tab||null;}
 setActivePage(tab){this.tab=tab;}
 async newTab(url='about:blank'){
  if(url!=='about:blank')validateNavigation(url);
  const tab=await (await connection()).createTab(url,false,true);owned.add(tab);return tab;
 }
 async listTabs(){return (await (await connection()).listTargets()).filter(t=>t.type==='page'||!t.type).map(t=>({page:t.targetId,url:t.url}));}
 async closeTab(tab){
  if(!owned.has(tab))throw Error('TASK_TAB_NOT_OWNED');
  const c=await connection();await c.closeTarget(tab);owned.delete(tab);sessions.delete(tab);captures.delete(tab);
  if(!owned.size)await closeTransport();
 }
 async evaluate(expression){return (await connection()).evalRaw(await sessionFor(this.tab),expression);}
 async startNetworkCapture(filter){
  const c=await connection(), sid=await sessionFor(this.tab);
  if(captures.has(this.tab)){const old=captures.get(this.tab);old.clear?.();}
  const capture={requests:new Map(),rows:[],pending:new Set(),remove:[]};captures.set(this.tab,capture);
  const push=(entry)=>{if(entry.queued)return;entry.queued=true;capture.rows.push(entry);};
  capture.remove.push(c.on('Network.requestWillBeSent|'+sid,p=>{
   const req=p.request||{};if(filter&&!String(req.url||'').includes(filter))return;
   capture.requests.set(p.requestId,{url:req.url,method:req.method,requestHeaders:req.headers||{},requestBody:req.postData||null,responseStatus:null,responseBody:null,responseBodyTruncated:false});
  }));
  capture.remove.push(c.on('Network.requestWillBeSentExtraInfo|'+sid,p=>{const e=capture.requests.get(p.requestId);if(e)e.requestHeaders={...e.requestHeaders,...p.headers};}));
  capture.remove.push(c.on('Network.responseReceived|'+sid,p=>{const e=capture.requests.get(p.requestId);if(e){e.responseStatus=p.response.status;if([403,429].includes(e.responseStatus))push(e);}}));
  capture.remove.push(c.on('Network.loadingFinished|'+sid,async p=>{
   const e=capture.requests.get(p.requestId);if(!e)return;
   const pending=(async()=>{try{const body=await c.send('Network.getResponseBody',{requestId:p.requestId},sid);const text=body.base64Encoded?Buffer.from(body.body,'base64').toString('utf8'):body.body;e.responseBodyTruncated=Buffer.byteLength(text||'','utf8')>16*1024*1024;e.responseBody=e.responseBodyTruncated?null:text;e.responsePreview=e.responseBody;push(e);}catch{e.responseBodyTruncated=true;push(e);}})();
   capture.pending.add(pending);try{await pending;}finally{capture.pending.delete(pending);}
  }));
  capture.clear=()=>{for(const remove of capture.remove)remove();};
  await c.send('Network.enable',{maxTotalBufferSize:64*1024*1024,maxResourceBufferSize:16*1024*1024},sid);return true;
 }
 async readNetworkCapture(){const capture=captures.get(this.tab);if(!capture)return[];await Promise.all([...capture.pending]);const rows=capture.rows.splice(0);return rows.map(({queued,...row})=>row);}
}
function validateNavigation(url){const u=new URL(url);if(u.protocol!=='https:'||!['item.jd.com','www.jd.com','passport.jd.com','cfe.m.jd.com','pc-frequent-pro.pf.jd.com'].includes(u.hostname)||u.username||u.password)throw Error('COLLECTION_NAVIGATION_NOT_ALLOWED');}
export async function sendCommandFull(command,params){
 if(command!=='navigate'||params.session!==context?.session)throw Error('COLLECTION_BROWSER_COMMAND_UNSUPPORTED');validateNavigation(params.url);
 const c=await connection();await c.navigate(await sessionFor(params.page),params.url);return{ok:true};
}
export async function closeTransport(){for(const capture of captures.values())capture.clear?.();captures.clear();sessions.clear();if(client)client.close();client=null;connecting=null;}
