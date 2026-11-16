if(process.argv.includes('--help')){console.log('click_probe.mjs --root <output> [original parameters]; owned task browser metadata required for live collection');process.exit(0);}
/** One normal page load; captures the complete native response before judging price availability. */
import fs from 'node:fs';import path from 'node:path';import {pathToFileURL} from 'node:url';
import {validate} from './request_policy.mjs';
import {taskContext,loadBrowserTransport,resolveStage} from './task_context.mjs';import {parseOptions} from './collection_policy.mjs';
import {openNativePage} from './native_page.mjs';import {acquireRunnerLock} from './runner_lock.mjs';
const options=parseOptions(process.argv.slice(2));const root=path.resolve(options.root);
const stage=options.stateDir?path.resolve(options.stateDir):resolveStage(root);
const context=taskContext(stage);
function atomic(file,value){fs.mkdirSync(path.dirname(file),{recursive:true});const tmp=file+'.pending';fs.writeFileSync(tmp,JSON.stringify(value,null,2),'utf8');fs.renameSync(tmp,file)}
let release,opened,result;
try{
 release=acquireRunnerLock(stage);const {Page,sendCommandFull,closeTransport}=await loadBrowserTransport(context);
 const owner=new Page(context.session,context.idleTimeout,undefined,'background');
 opened=await openNativePage(owner,Page,sendCommandFull,context,context.probeSku);
 if(!opened.result.ok)result=opened.result;
 else{
  const data=opened.result.data;
  try{
   validate(context.probeSku,data);
   const file=path.join(stage,'data',data.responseSku+'.json');
   if(!fs.existsSync(file))atomic(file,{source:'live_native_page',collectedAt:new Date().toISOString(),data});
   result={ok:true,sku:data.responseSku,arrival:data.pp,priceSource:data.priceSource};
  }catch(e){result={ok:false,reason:e.message,sku:data.responseSku}}
 }
}catch(e){result={ok:false,reason:['ANOTHER_RUNNER_OR_UNRESOLVED_LOCK','NETWORK_CAPTURE_UNSUPPORTED'].includes(e.message)?e.message:'LOCAL_OR_TRANSPORT_ERROR'}}
finally{
 if(opened){try{await opened.page.closeTab(opened.tab)}catch{result.cleanupPendingTab=opened.tab}}
 release?.();
}
result.checkedAt=new Date().toISOString();
if(result.reason!=='ANOTHER_RUNNER_OR_UNRESOLVED_LOCK')atomic(path.join(stage,'click_probe_status.json'),result);
console.log(JSON.stringify(result));
