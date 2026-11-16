const fs=require('node:fs');
const path=require('node:path');
const credentialKey=/cookie|token|authorization|api[_-]?key|secret|password|auth[_-]?code/i;
function hasCredentials(value){if(Array.isArray(value))return value.some(hasCredentials);if(value&&typeof value==='object')return Object.entries(value).some(([k,v])=>credentialKey.test(k)||hasCredentials(v));return false;}
function session(endpoint) {
  const file=process.env.HEIDENG_MERCHANT_BROWSER_CONFIG;
  const home=process.env.HEIDENG_MERCHANT_HOME;
  if(!file || !home) throw Error('merchant-browser-session-required');
  let cfg;try{cfg=JSON.parse(fs.readFileSync(file,'utf8').replace(/^\uFEFF/,''));}catch{throw Error('merchant-browser-session-required');}
  if(hasCredentials(cfg))throw Error('credential-fields-not-accepted');
  if(cfg.owned!==true || !(cfg.isolated===true || cfg.verifiedReuse===true) || typeof cfg.contextId!=='string' || !cfg.contextId || !cfg.identity?.shopName || !/^\d+$/.test(String(cfg.identity.venderId||''))) throw Error('merchant-browser-session-required');
  let base,profile;try{base=path.resolve(fs.realpathSync(home),'browser-profiles');profile=fs.realpathSync(cfg.profileDir);}catch{throw Error('merchant-browser-session-required');}
  const rel=path.relative(base,profile);if(!rel || rel.startsWith('..') || path.isAbsolute(rel)) throw Error('merchant-browser-session-required');
  let u;try{u=new URL(endpoint);}catch{throw Error('merchant-cdp-endpoint-required');}
  if(u.protocol!=='http:' || !['127.0.0.1','localhost','[::1]'].includes(u.hostname) || !u.port || u.username || u.password || u.search || u.hash || endpoint.replace(/\/$/,'')!==String(cfg.cdpEndpoint||'').replace(/\/$/,'')) throw Error('merchant-cdp-endpoint-required');
  return cfg;
}
function validatePlan(plan,kind,endpoint) {
 const cfg=session(endpoint);const allowed=new Set(JSON.parse(fs.readFileSync(path.join(__dirname,'../references/readonly-plan-urls.json'),'utf8')).urls);
 if(!Array.isArray(plan)||!plan.length)throw Error('original-readonly-plan-required');
 for(const item of plan){
  if(hasCredentials(item.body))throw Error('credential-fields-not-accepted');
  if(!/^[A-Za-z0-9_-]+$/.test(item.name||'')||!allowed.has(item.url)||!['GET','POST'].includes(item.method||'POST'))throw Error('original-readonly-plan-required');
  if(kind==='jzt'&&Object.hasOwn(item.body||{},'pinIds')&&(!Array.isArray(item.body.pinIds)||!item.body.pinIds.length))throw Error('merchant-ad-account-mismatch');
  if(kind==='jzt'&&Array.isArray(item.body?.pinIds)&&(!cfg.jztPinId||item.body.pinIds.some(x=>String(x)!==String(cfg.jztPinId))))throw Error('merchant-ad-account-mismatch');
 }
 return cfg;
}
function responseText(text){
 let value;try{value=JSON.parse(text);}catch{return JSON.stringify({unavailable:'non-json-or-login-response'});}
 const secret=/cookie|token|authorization|api[_-]?key|secret|password|auth[_-]?code/i;
 function clean(v){if(Array.isArray(v))return v.map(clean);if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).map(([k,x])=>[k,secret.test(k)?'[REDACTED]':clean(x)]));return v;}
 return JSON.stringify(clean(value));
}
module.exports={session,validatePlan,responseText};
