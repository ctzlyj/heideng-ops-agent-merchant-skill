const merchantBrowser=require('./merchant-browser.cjs');
const fs = require('fs');
const path = require('path');
const { Cdp } = require('./cdp-lib.js');
const { zguard, portFromCdp } = require('./guard.js');
const CDP = process.env.SHOP_CDP;
const args = process.argv.slice(2);
if(args.includes('--help')){console.log('jzt-run.js --plan <original plan> --out <task directory> (owned merchant browser config required)');process.exit(0);}
const getArg = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const PLAN = getArg('--plan');
const OUT = getArg('--out');
const NAV = getArg('--nav', 'https://jzt.jd.com/report/index.html#/rtb/basic');
const SETTLE = Number(getArg('--settle', '28000'));

(async () => {
  const plan = JSON.parse(fs.readFileSync(PLAN, 'utf8'));
  merchantBrowser.validatePlan(plan,'jzt',CDP);

  fs.mkdirSync(OUT, { recursive: true });
  const cdp = await Cdp.connect(CDP);
  const PORT = portFromCdp(CDP); zguard(PORT);
  const targetId = await cdp.createTab('about:blank', false, true);
  const sessionId = await cdp.attach(targetId);
  await cdp.send('Emulation.setFocusEmulationEnabled', { enabled: true }, sessionId).catch(() => {});
  await cdp.send('Page.enable', {}, sessionId);
  await cdp.navigate(sessionId, NAV);
  await cdp.waitReady(sessionId, SETTLE, 200000);

  const results = [];
  for (const item of plan) {
    const script = `(function(){ return new Promise(function(res){ var x=new XMLHttpRequest(); x.open(${JSON.stringify(item.method || 'POST')},${JSON.stringify(item.url)},true); x.withCredentials=true; x.setRequestHeader('Content-Type','application/json;charset=UTF-8'); x.timeout=60000; x.onreadystatechange=function(){ if(x.readyState===4){ res({status:x.status, text:(x.responseText||'')}); } }; x.ontimeout=function(){ res({status:'timeout'}); }; x.onerror=function(){ res({status:'error'}); }; x.send(${JSON.stringify(item.body ? JSON.stringify(item.body) : null)}); }); })()`;
    let r;
    try { r = await cdp.evalRaw(sessionId, script, 90000); } catch (e) { r = { status: 'eval-error', text: e.message }; }
    const rec = { name: item.name, url: item.url, postData: item.body || null, status: r.status, text: merchantBrowser.responseText(r.text) };
    fs.writeFileSync(path.join(OUT, item.name + '.json'), JSON.stringify(rec, null, 1), 'utf8');
    let ok = false, note = '';
    try { const j = JSON.parse(r.text); ok = j.code === 1 || j.success === true; note = 'code=' + j.code + ' rows=' + (((j.data || {}).datas || []).length); } catch (e) { note = 'noparse len=' + ((r.text || '').length); }
    results.push({ name: item.name, status: r.status, ok, note });
    console.log(JSON.stringify(results[results.length - 1]));
  }
  await cdp.closeTarget(targetId);
  cdp.close();
  zguard(PORT);
  console.log('DONE', OUT);
})().catch((e) => { console.error('FATAL', e.stack); process.exit(1); });
