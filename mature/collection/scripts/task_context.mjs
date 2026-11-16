import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
/** Validates the saved task-tab context; credentials never enter this file. */
export function taskContext(stage){
 const p=path.join(stage,'browser_context.json');
 if(!fs.existsSync(p))throw Error('TASK_BROWSER_CONTEXT_MISSING');
 let c;try{c=JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''))}catch{throw Error('TASK_BROWSER_CONTEXT_INVALID')}
 if(!c.session||typeof c.session!=='string'||/[^A-Za-z0-9_-]/.test(c.session))throw Error('TASK_BROWSER_CONTEXT_INVALID');
 if(!/^[A-F0-9]{32}$/.test(String(c.tab||'')))throw Error('TASK_BROWSER_CONTEXT_INVALID');
 if(c.windowMode!=='background'||!Number.isFinite(Number(c.idleTimeout))||Number(c.idleTimeout)<7200)throw Error('TASK_BROWSER_CONTEXT_INVALID');
 if(!/^\d{8,}$/.test(String(c.probeSku||'')))throw Error('TASK_BROWSER_CONTEXT_INVALID');

 return c;
}

/** Path plumbing only; Python and Node use the same per-output batch namespace. */
export function resolveStage(root, explicit=null){
 const home=process.env.HEIDENG_MERCHANT_HOME;
 if(!home)throw Error('HEIDENG_MERCHANT_HOME_REQUIRED');
 const canonical=p=>fs.existsSync(p)?fs.realpathSync(p):path.resolve(p);
 const base=path.join(canonical(home),'mature','collection','batches');
 const selected=explicit||process.env.HEIDENG_COLLECTION_STATE_DIR;
 const stage=selected?canonical(selected):path.join(base,createHash('sha256').update(canonical(root),'utf8').digest('hex'));
 const rel=path.relative(base,stage);
 if(!rel||rel==='..'||rel.startsWith('..'+path.sep)||path.isAbsolute(rel))throw Error('COLLECTION_STATE_OUTSIDE_HOME');
 return stage;
}
/** No bundled browser, implicit module search, auth or vendor preload. */
export async function loadBrowserTransport(context=null){
 const supplied=process.env.HEIDENG_COLLECTION_BROWSER_TRANSPORT;
 if(!supplied){const transport=await import('./owned_cdp_transport.mjs');await transport.configure(context);return transport;}
 if(!path.isAbsolute(supplied))throw Error('COLLECTION_BROWSER_TRANSPORT_ABSOLUTE_REQUIRED');
 let transport;
 try{transport=await import(pathToFileURL(supplied).href)}catch{throw Error('COLLECTION_BROWSER_TRANSPORT_LOAD_FAILED')}
 if(typeof transport.Page!=='function'||typeof transport.sendCommandFull!=='function')throw Error('COLLECTION_BROWSER_TRANSPORT_CONTRACT_INVALID');
 for(const method of ['setActivePage','startNetworkCapture','readNetworkCapture','evaluate','newTab','listTabs','closeTab']){
  if(typeof transport.Page.prototype[method]!=='function')throw Error('COLLECTION_BROWSER_TRANSPORT_CONTRACT_INVALID');
 }
 if(context&&typeof transport.configure==='function')await transport.configure(context);
 return transport;
}
