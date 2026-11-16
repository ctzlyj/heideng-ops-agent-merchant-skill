"""Agent-operated interface. Merchants describe goals rather than type commands."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from . import VERSION,SKILL_NAME
from .safety import SafetyError,atomic_json,read_json,redact
from .state import merchant_home
from .official import OfficialClient
from .operations import Operations
from .products import ProductService
from .product_schema import ProductSchemaService
from .schema_edit import EditService
from .materials import MaterialService
from .sku_materials import SkuMaterialService
from .shop_material_audit import ShopMaterialAudit
from .shop_material_execution import ShopMaterialExecution
from .short_titles import ShortTitlePlans
from .short_title_imports import ShortTitleImports
from .publish_support import PublishSupport
from .publishing import PublishService
from .publication_contract import read_input_json
from .public_output import public_result
from .auth_manager import AuthManager
from .providers import MediaConfiguration
from .video_source import VideoSource
from .video_runtime import VideoRuntime
from .video_probe import probe_video
from .video_handoff import preflight_video
from .video_delivery import VideoDelivery
from .video_binding import VideoBindingService
from .catalog import load_catalog,route
from .updates import ReleaseUpdates,github_json
from .workflows import read_rows,diagnose_rows,compare_exact_specs,prepare_listing,material_audit,package_snapshot,attach_video

def _json_file(value):
 if not value:return None
 result=read_json(Path(value))
 if result is None:raise SafetyError('input-json-not-found')
 return result

def parser():
 p=argparse.ArgumentParser(description='黑灯运营智能体商家版：由Agent操作，商家只描述目标')
 p.add_argument('--home');p.add_argument('--json',action='store_true');sub=p.add_subparsers(dest='command',required=True)
 sp=sub.add_parser('short-title-plan');sp.add_argument('--audit-id',required=True);sp.add_argument('--changes')
 sp=sub.add_parser('short-title-status');sp.add_argument('--plan-id',required=True)
 sp=sub.add_parser('short-title-rows');sp.add_argument('--plan-id',required=True);sp.add_argument('--page',type=int,default=1);sp.add_argument('--page-size',type=int,default=50);sp.add_argument('--view',choices=['coverage','chunks','siblings'],default='coverage')
 sp=sub.add_parser('short-title-workbooks');sp.add_argument('--plan-id',required=True);sp.add_argument('--template',required=True)
 sp=sub.add_parser('short-title-worker-start');sp.add_argument('--plan-id',required=True);sp.add_argument('--foreground',action='store_true')
 for action in ('resume','status','command-status','approve','execute','recover','results','effects','stop','repair-plan','repair-approve'):
  sp=sub.add_parser('short-title-worker-'+action);sp.add_argument('--worker-id',required=True)
  if action=='command-status':sp.add_argument('--request-id',required=True)
  elif action not in ('resume','status'):
   sp.add_argument('--request-id')
   if action!='stop':sp.add_argument('--import-id',required=True);sp.add_argument('--fingerprint',required=True)
   if action in ('approve','repair-approve'):sp.add_argument('--confirm',action='store_true');sp.add_argument('--ttl-seconds',type=int,default=900)
   if action=='repair-plan':sp.add_argument('--changes',required=True)
   if action=='repair-approve':sp.add_argument('--repair-plan-id',required=True);sp.add_argument('--repair-fingerprint',required=True)
 for action in ('status','rows'):
  sp=sub.add_parser('short-title-repair-'+action);sp.add_argument('--import-id',required=True);sp.add_argument('--repair-plan-id',required=True)
  if action=='rows':sp.add_argument('--page',type=int,default=1);sp.add_argument('--page-size',type=int,default=50);sp.add_argument('--view',choices=('changes','siblings'),default='changes')
 sp=sub.add_parser('short-title-import-plan');sp.add_argument('--plan-id',required=True);sp.add_argument('--source-id',required=True)
 sp=sub.add_parser('short-title-import-approve');sp.add_argument('--import-id',required=True);sp.add_argument('--fingerprint',required=True);sp.add_argument('--confirm',action='store_true');sp.add_argument('--ttl-seconds',type=int,default=900)
 sp=sub.add_parser('short-title-import-status');sp.add_argument('--import-id',required=True)
 sp=sub.add_parser('short-title-import-rows');sp.add_argument('--import-id',required=True);sp.add_argument('--page',type=int,default=1);sp.add_argument('--page-size',type=int,default=50);sp.add_argument('--view',choices=['batches','changes','results','effects'],default='batches')
 sp=sub.add_parser('shop-material-plan');sp.add_argument('--audit-id',required=True);sp.add_argument('--changes');sp.add_argument('--target-slots')
 sp=sub.add_parser('shop-material-approve');sp.add_argument('--plan-id',required=True);sp.add_argument('--fingerprint',required=True);sp.add_argument('--confirm',action='store_true');sp.add_argument('--ttl-seconds',type=int,default=900)
 for name in ('shop-material-execute','shop-material-status','shop-material-rows'):
  sp=sub.add_parser(name);sp.add_argument('--plan-id',required=True)
  if name=='shop-material-status':sp.add_argument('--refresh',action='store_true')
  if name=='shop-material-rows':sp.add_argument('--page',type=int,default=1);sp.add_argument('--page-size',type=int,default=50);sp.add_argument('--view',choices=['coverage','chunks'],default='coverage')
 sa=sub.add_parser('sku-material-shop-audit');sa.add_argument('--profile',required=True);sa.add_argument('--threshold',type=int,default=89);sa.add_argument('--max-products',type=int,default=10000);sa.add_argument('--max-skus',type=int,default=100000);sa.add_argument('--max-pages',type=int,default=1000);sa.add_argument('--no-health',action='store_true')
 ss=sub.add_parser('sku-material-shop-status');ss.add_argument('--audit-id',required=True)
 sp=sub.add_parser('sku-material-shop-rows');sp.add_argument('--audit-id',required=True);sp.add_argument('--page',type=int,default=1);sp.add_argument('--page-size',type=int,default=50);sp.add_argument('--include-offline',action='store_true');sp.add_argument('--only',choices=('all','low-score','gaps','pending','rejected','unscored','short-title','unobserved'),default='all')
 for name in ('sku-material-audit','sku-material-plan'):
  mp=sub.add_parser(name);mp.add_argument('--profile',required=True);mp.add_argument('--product-id',required=True)
  if name=='sku-material-audit':mp.add_argument('--include-health',action='store_true')
  else:mp.add_argument('--changes',required=True)
 ma=sub.add_parser('sku-material-approve');ma.add_argument('--plan-id',required=True);ma.add_argument('--fingerprint',required=True);ma.add_argument('--confirm',action='store_true');ma.add_argument('--ttl-seconds',type=int,default=900)
 for name in ('sku-material-execute','sku-material-status'):
  mp=sub.add_parser(name);mp.add_argument('--plan-id',required=True)
  if name=='sku-material-status':mp.add_argument('--refresh',action='store_true')
 mz=sub.add_parser('material-zones');mz.add_argument('--profile',required=True);mz.add_argument('--zone-type',type=int,choices=(1,2))
 for name in ('material-categories','material-images'):
  mp=sub.add_parser(name);mp.add_argument('--profile',required=True);mp.add_argument('--zone-id',required=True);mp.add_argument('--filters');mp.add_argument('--page-size',type=int,default=50);mp.add_argument('--max-pages',type=int,default=100);mp.add_argument('--start-page',type=int,default=1)
 md=sub.add_parser('material-detail');md.add_argument('--profile',required=True);md.add_argument('--zone-id',required=True);md.add_argument('--image-id',required=True)
 mu=sub.add_parser('material-upload-plan');mu.add_argument('--profile',required=True);mu.add_argument('--image',required=True);mu.add_argument('--zone-id',required=True);mu.add_argument('--category-id',required=True);mu.add_argument('--name')
 ms=sub.add_parser('material-upload-status');ms.add_argument('--task-id',required=True);ms.add_argument('--refresh',action='store_true')
 rv=sub.add_parser('task-result-readback');rv.add_argument('--task-id',required=True)
 for name in ('onboarding','catalog','media-status','video-source-status','update-check','update-apply','video-source-check','video-runtime-status','video-runtime-prepare'):sub.add_parser(name)
 ip=sub.add_parser('image-plan');ip.add_argument('--request',required=True)
 ia=sub.add_parser('image-approve');ia.add_argument('--plan-id',required=True);ia.add_argument('--fingerprint',required=True);ia.add_argument('--confirm',action='store_true')
 for name in ('image-execute','image-status'):
  ip=sub.add_parser(name);ip.add_argument('--plan-id',required=True)
 r=sub.add_parser('route');r.add_argument('request')
 d=sub.add_parser('doctor');d.add_argument('--install-cli',action='store_true')
 od=sub.add_parser('official-doc');od.add_argument('skill_id');od.add_argument('--reference',default='SKILL.md');od.add_argument('--refresh',action='store_true')
 connect=sub.add_parser('shop-connect');connect.add_argument('--profile',required=True);connect.add_argument('--shop-name',required=True);connect.add_argument('--vender-id',required=True)
 auth=sub.add_parser('auth-plan');auth.add_argument('--profile',required=True);auth.add_argument('--shop-name',required=True);auth.add_argument('--vender-id')
 for name in ('auth-start','ensure-shop'):
  c=sub.add_parser(name);c.add_argument('--shop-name',required=True);c.add_argument('--vender-id');c.add_argument('--foreground',action='store_true');c.add_argument('--wait',action='store_true');c.add_argument('--wait-timeout',type=int,default=960);c.add_argument('--browser-controller')
 for name in ('auth-status','auth-observe','auth-cancel','auth-recover'):
  c=sub.add_parser(name);c.add_argument('--task-id',required=True)
 retry=sub.add_parser('auth-restart');retry.add_argument('--task-id',required=True);retry.add_argument('--foreground',action='store_true');retry.add_argument('--wait',action='store_true');retry.add_argument('--wait-timeout',type=int,default=960);retry.add_argument('--browser-controller')
 confirm=sub.add_parser('auth-confirm-shop');confirm.add_argument('--task-id',required=True);confirm.add_argument('--shop-name',required=True);confirm.add_argument('--vender-id',required=True);confirm.add_argument('--fingerprint',required=True);confirm.add_argument('--confirm',action='store_true')
 reconcile=sub.add_parser('auth-reconcile');reconcile.add_argument('--task-id',required=True)
 cp=sub.add_parser('auth-prove-cleanup');cp.add_argument('--task-id',required=True);cp.add_argument('--browser-controller')
 ab=sub.add_parser('auth-bind-alias');ab.add_argument('--shop-name',required=True);ab.add_argument('--profile',required=True);ab.add_argument('--confirm',action='store_true')
 aw=sub.add_parser('auth-wait');aw.add_argument('--task-id',required=True);aw.add_argument('--wait-timeout',type=int,default=960)
 plan=sub.add_parser('task-plan');plan.add_argument('--profile',required=True);plan.add_argument('--operation',required=True);plan.add_argument('--verification');plan.add_argument('--precondition');plan.add_argument('--online-verification');plan.add_argument('--result-verification')
 approval=sub.add_parser('task-approve');approval.add_argument('--task-id',required=True);approval.add_argument('--fingerprint',required=True);approval.add_argument('--confirm',action='store_true')
 for name in ('task-execute','task-status'):
  c=sub.add_parser(name);c.add_argument('--task-id',required=True)
 rb=sub.add_parser('task-readback');rb.add_argument('--task-id',required=True);rb.add_argument('--query',required=True);rb.add_argument('--expected',required=True)
 for name in ('product-list','sku-list','health-list'):
  c=sub.add_parser(name);c.add_argument('--profile',required=True);c.add_argument('--page-size',type=int,default=20);c.add_argument('--max-pages',type=int,default=100);c.add_argument('--start-page',type=int,default=1)
  if name=='sku-list':c.add_argument('--product-id',required=True)
  else:c.add_argument('--filters')
 detail=sub.add_parser('product-detail');detail.add_argument('--profile',required=True);detail.add_argument('--product-id',required=True)
 schema=sub.add_parser('product-schema');schema.add_argument('--profile',required=True);schema.add_argument('--product-id',required=True)
 draft=sub.add_parser('schema-image-draft');draft.add_argument('--capture-id',required=True);draft.add_argument('--changes',required=True)
 for command,flag in (('schema-capture-status','capture-id'),('schema-draft-status','draft-id')):
  c=sub.add_parser(command);c.add_argument('--'+flag,required=True)
 compiled=sub.add_parser('schema-compile');compiled.add_argument('--capture-id',required=True)
 prepared=sub.add_parser('schema-edit-prepare');prepared.add_argument('--capture-id',required=True)
 baseline=sub.add_parser('schema-edit-baseline');baseline.add_argument('--capture-id',required=True);baseline.add_argument('--schema',required=True);baseline.add_argument('--bindings',required=True);baseline.add_argument('--sale-sources',required=True)
 ev=sub.add_parser('schema-edit-validation-plan');ev.add_argument('--baseline-id',required=True);ev.add_argument('--changes',required=True)
 ep=sub.add_parser('schema-edit-plan');ep.add_argument('--validation-task-id',required=True)
 es=sub.add_parser('schema-edit-status');es.add_argument('--task-id',required=True);es.add_argument('--refresh',action='store_true')
 eo=sub.add_parser('schema-edit-online');eo.add_argument('--task-id',required=True)
 cats=sub.add_parser('publish-categories');cats.add_argument('--profile',required=True);cats.add_argument('--ids')
 brands=sub.add_parser('publish-brands');brands.add_argument('--profile',required=True);brands.add_argument('--category-id',required=True);brands.add_argument('--name');brands.add_argument('--max-pages',type=int,default=100);brands.add_argument('--start-page',type=int,default=1)
 context=sub.add_parser('publish-context');context.add_argument('--profile',required=True);context.add_argument('--category-id',required=True);context.add_argument('--brand-id',required=True)
 validation=sub.add_parser('publish-validation-plan');validation.add_argument('--profile',required=True);validation.add_argument('--manifest',required=True);validation.add_argument('--schema',required=True);validation.add_argument('--spec-map',required=True);validation.add_argument('--asset-bindings',required=True)
 pub=sub.add_parser('publish-plan');pub.add_argument('--validation-task-id',required=True)
 for name in ('publish-validation-status','publish-status'):
  c=sub.add_parser(name);c.add_argument('--task-id',required=True)
 price=sub.add_parser('price-plan');price.add_argument('--profile',required=True);price.add_argument('--product-id',required=True);price.add_argument('--changes',required=True)
 price_status=sub.add_parser('price-status');price_status.add_argument('--task-id',required=True);price_status.add_argument('--refresh',choices=('none','pending','online'),default='none')
 online=sub.add_parser('task-online-readback');online.add_argument('--task-id',required=True)
 inspect=sub.add_parser('inspect-source');inspect.add_argument('--source',required=True);inspect.add_argument('--sheet')
 for name in ('diagnose','material-audit'):
  c=sub.add_parser(name);c.add_argument('--source',required=True);c.add_argument('--output',required=True);c.add_argument('--sheet');c.add_argument('--mapping')
 compare=sub.add_parser('compare');compare.add_argument('--source',required=True);compare.add_argument('--specs',required=True);compare.add_argument('--output',required=True)
 listing=sub.add_parser('prepare-listing');listing.add_argument('--product',required=True);listing.add_argument('--source-root',required=True);listing.add_argument('--output',required=True)
 collect=sub.add_parser('package-snapshot');collect.add_argument('--snapshot',required=True);collect.add_argument('--output',required=True)
 for name in ('video-binding-preview','video-binding-plan'):
  vb=sub.add_parser(name);vb.add_argument('--profile',required=True);vb.add_argument('--product-id',required=True);vb.add_argument('--session-id',required=True)
  if name=='video-binding-plan':vb.add_argument('--review',required=True)
 vb=sub.add_parser('video-binding-approve');vb.add_argument('--plan-id',required=True);vb.add_argument('--fingerprint',required=True);vb.add_argument('--confirm',action='store_true');vb.add_argument('--ttl-seconds',type=int,default=900)
 for name in ('video-binding-execute','video-binding-status'):
  vb=sub.add_parser(name);vb.add_argument('--plan-id',required=True)
  if name=='video-binding-status':vb.add_argument('--refresh',action='store_true')
 vd=sub.add_parser('video-delivery-plan');vd.add_argument('--profile',required=True);vd.add_argument('--manifest',required=True);vd.add_argument('--zone-id',required=True);vd.add_argument('--name')
 va=sub.add_parser('video-delivery-approve');va.add_argument('--session-id',required=True);va.add_argument('--fingerprint',required=True);va.add_argument('--confirm',action='store_true');va.add_argument('--ttl-seconds',type=int,default=900)
 vc=sub.add_parser('video-delivery-cancel');vc.add_argument('--session-id',required=True);vc.add_argument('--fingerprint',required=True);vc.add_argument('--confirm',action='store_true')
 for name in ('video-delivery-execute','video-delivery-status'):
  vr=sub.add_parser(name);vr.add_argument('--session-id',required=True)
  if name=='video-delivery-status':vr.add_argument('--refresh',action='store_true')
 vp=sub.add_parser('probe-video');vp.add_argument('--video',required=True)
 vf=sub.add_parser('video-preflight');vf.add_argument('--manifest',required=True)
 video=sub.add_parser('attach-video');video.add_argument('--manifest',required=True);video.add_argument('--video',required=True);video.add_argument('--cover');video.add_argument('--review')
 return p

def run(args):
 state=merchant_home(args.home);client=OfficialClient(state);ops=Operations(state,client);command=args.command
 if command=='update-check':return {k:v for k,v in ReleaseUpdates(state).check(VERSION).items() if k!='release'}
 if command=='update-apply':return ReleaseUpdates(state).apply(Path(__file__).resolve().parents[1])
 if command=='video-source-check':return VideoSource(state).discover(github_json)
 if command=='catalog':return load_catalog()
 if command=='route':return route(args.request)
 if command=='media-status':return MediaConfiguration(state).status()
 if command=='video-source-status':return VideoSource(state).status()
 if command=='image-plan':return MediaConfiguration(state).image_plan(_json_file(args.request))
 if command=='image-approve':return MediaConfiguration(state).image_approve(args.plan_id,args.fingerprint,confirmed=args.confirm)
 if command=='image-status':return MediaConfiguration(state).image_status(args.plan_id)
 if command=='image-execute':return MediaConfiguration(state).generation_request('image',{'planId':args.plan_id})
 if command=='doctor':
  install=client.install() if args.install_cli else None
  return {'status':'ready-for-local-workflows','version':VERSION,'officialCli':{'ready':client.ready(),'install':install},'media':MediaConfiguration(state).status(),'requiresEmployeeAccess':False,'shopAuthorization':'not-implied-by-installation'}
 if command=='onboarding':
  shop_capability=client.shop_capability()
  shop_hint='告诉我你想处理哪家店或哪份商品资料；需要新授权时，Agent先复用原连接器的宿主浏览器控制器；你只用京麦App扫码并完成平台本人确认，不配置控制器。' if shop_capability['authAvailable'] else shop_capability['guidance']
  return {'displayName':'黑灯运营智能体商家版','skill':SKILL_NAME,'version':VERSION,'requiresEmployeeAccess':False,'requiresManualCommands':False,'shopCapability':shop_capability,'officialCli':{'ready':client.ready()},'media':MediaConfiguration(state).status(),'steps':[{'id':'installed','text':'商家版已安装，可直接描述目标。'},{'id':'official-cli','text':'需要店铺查询或操作时，Agent自动安装校验官方京麦CLI；离线任务不需要店铺登录。' if shop_capability['authAvailable'] else '当前平台店铺官方链路不可用，不下载必然不能使用的授权运行时；可继续离线任务和外部生图。','action':None if client.ready() or not shop_capability['authAvailable'] else 'doctor --install-cli'},{'id':'goal','text':shop_hint},{'id':'models','text':'生图已接入LTS4AI / gpt-image-2.5；商家安全设置自己的Key并批准本次数量/预算后可执行，真实网关调用尚未实测；视频服务未选择。已有素材、报表分析和业务准备可继续，不读取员工Key。'}]}
 if command=='official-doc':return {'path':str(client.document(args.skill_id,args.reference,refresh=args.refresh)),'source':'official-policy-sha256-verified','execution':'read-rules-before-preparing-request'}
 if command=='shop-connect':return ops.connect(args.profile,args.shop_name,args.vender_id)
 if command=='auth-plan':return client.login_plan(args.profile,args.shop_name,args.vender_id)
 if command in ('auth-start','ensure-shop'):
  manager=AuthManager(state,client=client)
  method=manager.start if command=='auth-start' else manager.ensure_shop
  wait_options={'wait':True,'wait_timeout':args.wait_timeout,'progress':auth_progress} if args.wait else {}
  controller_options={'browser_controller':_json_file(args.browser_controller)} if args.browser_controller else {}
  return method(args.shop_name,vender_id=args.vender_id,foreground=args.foreground,**wait_options,**controller_options)
 if command=='auth-restart':
  wait_options={'wait':True,'wait_timeout':args.wait_timeout,'progress':auth_progress} if args.wait else {}
  controller_options={'browser_controller':_json_file(args.browser_controller)} if args.browser_controller else {}
  return AuthManager(state,client=client).restart(args.task_id,foreground=args.foreground,**wait_options,**controller_options)
 if command=='auth-confirm-shop':return AuthManager(state,client=client).confirm_shop(args.task_id,args.shop_name,args.vender_id,args.fingerprint,confirmed=args.confirm)
 if command=='auth-reconcile':return AuthManager(state,client=client).reconcile(args.task_id)
 if command=='auth-prove-cleanup':
  controller_options={'browser_controller':_json_file(args.browser_controller)} if args.browser_controller else {}
  return AuthManager(state,client=client).prove_cleanup(args.task_id,**controller_options)
 if command=='auth-bind-alias':return AuthManager(state,client=client).bind_alias(args.shop_name,args.profile,confirmed=args.confirm)
 if command=='auth-wait':return AuthManager(state,client=client).wait(args.task_id,timeout=args.wait_timeout,progress=auth_progress)
 if command in ('auth-status','auth-observe','auth-cancel','auth-recover'):
  return getattr(AuthManager(state,client=client),command.removeprefix('auth-'))(args.task_id)
 if command=='task-plan':return ops.prepare(args.profile,_json_file(args.operation),_json_file(args.verification),precondition=_json_file(args.precondition),online_verification=_json_file(args.online_verification),result_verification=_json_file(args.result_verification))
 if command=='task-approve':return ops.approve(args.task_id,args.fingerprint,confirmed=args.confirm)
 if command=='task-execute':return ops.execute(args.task_id)
 if command=='short-title-plan':return ShortTitlePlans(state,client).prepare(args.audit_id,[] if args.changes is None else _json_file(args.changes))
 if command=='short-title-status':return ShortTitlePlans(state,client).status(args.plan_id)
 if command=='short-title-rows':return ShortTitlePlans(state,client).rows(args.plan_id,page=args.page,page_size=args.page_size,view=args.view)
 if command=='short-title-workbooks':return ShortTitlePlans(state,client).compile(args.plan_id,args.template)
 if command.startswith('short-title-worker-'):
  from .short_title_worker_service import ShortTitleWorkerService
  worker=ShortTitleWorkerService(state,client=client);action=command.removeprefix('short-title-worker-')
  if action=='start':return worker.start(args.plan_id,foreground=args.foreground)
  if action=='resume':return worker.resume(args.worker_id)
  if action=='status':return worker.status(args.worker_id)
  if action=='command-status':return worker.command_status(args.worker_id,args.request_id)
  return worker.command(args.worker_id,action,import_id=getattr(args,'import_id',None),fingerprint=getattr(args,'fingerprint',None),confirmed=getattr(args,'confirm',False),ttl=getattr(args,'ttl_seconds',900),request_id=args.request_id,changes=read_input_json(args.changes)[0] if getattr(args,'changes',None) is not None else None,repair_id=getattr(args,'repair_plan_id',None),repair_fingerprint=getattr(args,'repair_fingerprint',None))
 if command=='short-title-repair-status':return ShortTitleImports(state,client).repair_status(args.import_id,args.repair_plan_id)
 if command=='short-title-repair-rows':return ShortTitleImports(state,client).repair_rows(args.import_id,args.repair_plan_id,page=args.page,page_size=args.page_size,view=args.view)
 if command=='short-title-import-plan':return ShortTitleImports(state,client).prepare(args.plan_id,args.source_id)
 if command=='short-title-import-approve':return ShortTitleImports(state,client).approve(args.import_id,args.fingerprint,confirmed=args.confirm,ttl=args.ttl_seconds)
 if command=='short-title-import-status':return ShortTitleImports(state,client).status(args.import_id)
 if command=='short-title-import-rows':return ShortTitleImports(state,client).rows(args.import_id,page=args.page,page_size=args.page_size,view=args.view)
 if command=='shop-material-plan':return ShopMaterialExecution(state,client).prepare(args.audit_id,[] if args.changes is None else _json_file(args.changes),target_slots=None if args.target_slots is None else args.target_slots.split(','))
 if command=='shop-material-approve':return ShopMaterialExecution(state,client).approve(args.plan_id,args.fingerprint,confirmed=args.confirm,ttl_seconds=args.ttl_seconds)
 if command=='shop-material-execute':return ShopMaterialExecution(state,client).execute(args.plan_id)
 if command=='shop-material-status':return ShopMaterialExecution(state,client).status(args.plan_id,refresh=args.refresh)
 if command=='shop-material-rows':return ShopMaterialExecution(state,client).rows(args.plan_id,page=args.page,page_size=args.page_size,view=args.view)
 if command=='sku-material-shop-audit':
  service=ShopMaterialAudit(state,client);result=service.audit(args.profile,threshold=args.threshold,max_products=args.max_products,max_skus=args.max_skus,max_pages=args.max_pages,include_health=not args.no_health);return service.summary(result['auditId'])
 if command=='sku-material-shop-status':return ShopMaterialAudit(state,client).summary(args.audit_id)
 if command=='sku-material-shop-rows':return ShopMaterialAudit(state,client).page(args.audit_id,page=args.page,page_size=args.page_size,include_offline=args.include_offline,only=args.only)
 if command=='sku-material-audit':return SkuMaterialService(state,client).audit(args.profile,args.product_id,include_health=args.include_health)
 if command=='sku-material-plan':return SkuMaterialService(state,client).prepare(args.profile,args.product_id,_json_file(args.changes))
 if command=='sku-material-approve':return SkuMaterialService(state,client).approve(args.plan_id,args.fingerprint,confirmed=args.confirm,ttl_seconds=args.ttl_seconds)
 if command=='sku-material-execute':return SkuMaterialService(state,client).execute(args.plan_id)
 if command=='sku-material-status':return SkuMaterialService(state,client).status(args.plan_id,refresh=args.refresh)
 if command=='material-zones':return MaterialService(state,client).zones(args.profile,zone_type=args.zone_type)
 if command in ('material-categories','material-images'):
  service=MaterialService(state,client);options={'filters':_json_file(args.filters),'page_size':args.page_size,'max_pages':args.max_pages,'start_page':args.start_page}
  return service.categories(args.profile,args.zone_id,**options) if command=='material-categories' else service.images(args.profile,args.zone_id,**options)
 if command=='material-detail':return MaterialService(state,client).detail(args.profile,args.zone_id,args.image_id)
 if command=='material-upload-plan':return MaterialService(state,client).prepare_upload(args.profile,args.image,args.zone_id,args.category_id,name=args.name)
 if command=='material-upload-status':return MaterialService(state,client).upload_status(args.task_id,refresh=args.refresh)
 if command=='task-result-readback':return ops.verify_result(args.task_id)
 if command=='task-status':return ops.task(args.task_id)
 if command=='task-readback':return ops.readback(args.task_id,_json_file(args.query),_json_file(args.expected))
 if command=='task-online-readback':return ops.verify_online(args.task_id)
 if command=='product-detail':return ProductService(state,client).detail(args.profile,args.product_id)
 if command in ('product-list','sku-list','health-list'):
  service=ProductService(state,client);options={'page_size':args.page_size,'max_pages':args.max_pages,'start_page':args.start_page}
  if command=='sku-list':return service.list_skus(args.profile,args.product_id,**options)
  options['filters']=_json_file(args.filters)
  return service.list_products(args.profile,**options) if command=='product-list' else service.list_health(args.profile,**options)
 if command=='product-schema':return ProductSchemaService(state,client).capture_edit(args.profile,args.product_id)
 if command=='schema-image-draft':return ProductSchemaService(state,client).draft_images(args.capture_id,_json_file(args.changes))
 if command=='schema-capture-status':return ProductSchemaService(state,client).capture(args.capture_id)
 if command=='schema-draft-status':return ProductSchemaService(state,client).draft(args.draft_id)
 if command=='schema-compile':return ProductSchemaService(state,client).compile_capture(args.capture_id)
 if command=='schema-edit-prepare':return EditService(state,client).prepare_baseline(args.capture_id)
 if command=='schema-edit-baseline':return EditService(state,client).baseline(args.capture_id,read_input_json(args.schema)[0],read_input_json(args.bindings)[0],read_input_json(args.sale_sources)[0])
 if command=='schema-edit-validation-plan':return EditService(state,client).plan_validation(args.baseline_id,read_input_json(args.changes)[0])
 if command=='schema-edit-plan':return EditService(state,client).plan_edit(args.validation_task_id)
 if command=='schema-edit-status':return EditService(state,client).status(args.task_id,refresh=args.refresh)
 if command=='schema-edit-online':return EditService(state,client).verify_online(args.task_id)
 if command=='publish-categories':return {'items':PublishSupport(state,client).categories(args.profile,read_input_json(args.ids)[0] if args.ids else [0]),'source':'official-realtime-authorized-category-query','completeShopCatalog':False}
 if command=='publish-brands':return PublishSupport(state,client).brands(args.profile,args.category_id,name=args.name,max_pages=args.max_pages,start_page=args.start_page)
 if command=='publish-context':return PublishSupport(state,client).context(args.profile,args.category_id,args.brand_id)
 if command=='publish-validation-plan':return PublishService(state,client).plan_validation(args.profile,args.manifest,read_input_json(args.schema)[0],read_input_json(args.spec_map)[0],read_input_json(args.asset_bindings)[0])
 if command=='publish-validation-status':return PublishService(state,client).validation_status(args.task_id)
 if command=='publish-plan':return PublishService(state,client).plan_publish(args.validation_task_id)
 if command=='publish-status':return PublishService(state,client).status(args.task_id)
 if command=='price-plan':return ProductService(state,client).prepare_price(args.profile,args.product_id,_json_file(args.changes))
 if command=='price-status':return ProductService(state,client).price_status(args.task_id,refresh=args.refresh)
 if command=='inspect-source':
  rows=read_rows(args.source,args.sheet);return {'rowCount':len(rows),'columns':list(rows[0]),'sampleIdentifiers':[str(r.get('skuId',r.get('SPUID',''))) for r in rows[:3]],'source':'user-provided'}
 if command in ('diagnose','material-audit'):
  rows=read_rows(args.source,args.sheet);mapping=_json_file(args.mapping) or {}
  if mapping:rows=[{mapping.get(k,k):v for k,v in row.items()} for row in rows]
  result=diagnose_rows(rows) if command=='diagnose' else material_audit(rows);atomic_json(Path(args.output),result);return result
 if command=='compare':
  result=compare_exact_specs(read_rows(args.source),_json_file(args.specs));atomic_json(Path(args.output),result);return result
 if command=='prepare-listing':return prepare_listing(read_input_json(args.product)[0],args.source_root,args.output)
 if command=='package-snapshot':return package_snapshot(_json_file(args.snapshot),args.output)
 if command=='video-binding-preview':return VideoBindingService(state,client).preview(args.profile,args.product_id,args.session_id)
 if command=='video-binding-plan':return VideoBindingService(state,client).prepare(args.profile,args.product_id,args.session_id,review=_json_file(args.review))
 if command=='video-binding-approve':return VideoBindingService(state,client).approve(args.plan_id,args.fingerprint,confirmed=args.confirm,ttl_seconds=args.ttl_seconds)
 if command=='video-binding-execute':return VideoBindingService(state,client).execute(args.plan_id)
 if command=='video-binding-status':return VideoBindingService(state,client).status(args.plan_id,refresh=args.refresh)
 if command=='video-delivery-plan':return VideoDelivery(state,client).prepare(args.profile,args.manifest,args.zone_id,name=args.name)
 if command=='video-delivery-approve':return VideoDelivery(state,client).approve(args.session_id,args.fingerprint,confirmed=args.confirm,ttl_seconds=args.ttl_seconds)
 if command=='video-delivery-cancel':return VideoDelivery(state,client).cancel(args.session_id,args.fingerprint,confirmed=args.confirm)
 if command=='video-delivery-execute':return VideoDelivery(state,client).execute(args.session_id)
 if command=='video-delivery-status':return VideoDelivery(state,client).status(args.session_id,refresh=args.refresh)
 if command=='video-runtime-status':return VideoRuntime(state).status()
 if command=='video-runtime-prepare':return VideoRuntime(state).ensure()
 if command=='probe-video':return probe_video(state,args.video)
 if command=='video-preflight':return preflight_video(args.manifest,state=state)
 if command=='attach-video':return attach_video(args.manifest,args.video,args.cover,_json_file(args.review),state=state)
 raise SafetyError('unknown-command')

def auth_progress(result):
 print(json.dumps(public_result(redact(result)),ensure_ascii=False,allow_nan=False),flush=True)

def main(argv=None):
 for stream in (sys.stdout,sys.stderr):
  if hasattr(stream,"reconfigure"):stream.reconfigure(encoding="utf-8",errors="backslashreplace")
 try:
  result=run(parser().parse_args(argv));print(json.dumps(public_result(redact(result)),ensure_ascii=False,allow_nan=False));return 0
 except (SafetyError,ValueError,OSError) as error:
  print(json.dumps({'status':'blocked','error':redact(str(error)),'paidCalls':0,'employeeFallback':False},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
