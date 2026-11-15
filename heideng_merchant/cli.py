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
from .materials import MaterialService
from .public_output import public_result
from .auth_manager import AuthManager
from .providers import MediaConfiguration
from .video_source import VideoSource
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
 mz=sub.add_parser('material-zones');mz.add_argument('--profile',required=True);mz.add_argument('--zone-type',type=int,choices=(1,2))
 for name in ('material-categories','material-images'):
  mp=sub.add_parser(name);mp.add_argument('--profile',required=True);mp.add_argument('--zone-id',required=True);mp.add_argument('--filters');mp.add_argument('--page-size',type=int,default=50);mp.add_argument('--max-pages',type=int,default=100);mp.add_argument('--start-page',type=int,default=1)
 md=sub.add_parser('material-detail');md.add_argument('--profile',required=True);md.add_argument('--zone-id',required=True);md.add_argument('--image-id',required=True)
 mu=sub.add_parser('material-upload-plan');mu.add_argument('--profile',required=True);mu.add_argument('--image',required=True);mu.add_argument('--zone-id',required=True);mu.add_argument('--category-id',required=True);mu.add_argument('--name')
 ms=sub.add_parser('material-upload-status');ms.add_argument('--task-id',required=True);ms.add_argument('--refresh',action='store_true')
 rv=sub.add_parser('task-result-readback');rv.add_argument('--task-id',required=True)
 for name in ('onboarding','catalog','media-status','video-source-status','update-check','update-apply','video-source-check'):sub.add_parser(name)
 r=sub.add_parser('route');r.add_argument('request')
 d=sub.add_parser('doctor');d.add_argument('--install-cli',action='store_true')
 od=sub.add_parser('official-doc');od.add_argument('skill_id');od.add_argument('--reference',default='SKILL.md');od.add_argument('--refresh',action='store_true')
 connect=sub.add_parser('shop-connect');connect.add_argument('--profile',required=True);connect.add_argument('--shop-name',required=True);connect.add_argument('--vender-id',required=True)
 auth=sub.add_parser('auth-plan');auth.add_argument('--profile',required=True);auth.add_argument('--shop-name',required=True);auth.add_argument('--vender-id')
 for name in ('auth-start','ensure-shop'):
  c=sub.add_parser(name);c.add_argument('--shop-name',required=True);c.add_argument('--vender-id');c.add_argument('--foreground',action='store_true')
 for name in ('auth-status','auth-observe','auth-cancel','auth-recover'):
  c=sub.add_parser(name);c.add_argument('--task-id',required=True)
 retry=sub.add_parser('auth-restart');retry.add_argument('--task-id',required=True);retry.add_argument('--foreground',action='store_true')
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
 price=sub.add_parser('price-plan');price.add_argument('--profile',required=True);price.add_argument('--product-id',required=True);price.add_argument('--changes',required=True)
 price_status=sub.add_parser('price-status');price_status.add_argument('--task-id',required=True);price_status.add_argument('--refresh',choices=('none','pending','online'),default='none')
 online=sub.add_parser('task-online-readback');online.add_argument('--task-id',required=True)
 inspect=sub.add_parser('inspect-source');inspect.add_argument('--source',required=True);inspect.add_argument('--sheet')
 for name in ('diagnose','material-audit'):
  c=sub.add_parser(name);c.add_argument('--source',required=True);c.add_argument('--output',required=True);c.add_argument('--sheet');c.add_argument('--mapping')
 compare=sub.add_parser('compare');compare.add_argument('--source',required=True);compare.add_argument('--specs',required=True);compare.add_argument('--output',required=True)
 listing=sub.add_parser('prepare-listing');listing.add_argument('--product',required=True);listing.add_argument('--source-root',required=True);listing.add_argument('--output',required=True)
 collect=sub.add_parser('package-snapshot');collect.add_argument('--snapshot',required=True);collect.add_argument('--output',required=True)
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
 if command=='doctor':
  install=client.install() if args.install_cli else None
  return {'status':'ready-for-local-workflows','version':VERSION,'officialCli':{'ready':client.ready(),'install':install},'media':MediaConfiguration(state).status(),'requiresEmployeeAccess':False,'shopAuthorization':'not-implied-by-installation'}
 if command=='onboarding':
  return {'displayName':'黑灯运营智能体商家版','skill':SKILL_NAME,'version':VERSION,'requiresEmployeeAccess':False,'requiresManualCommands':False,'officialCli':{'ready':client.ready()},'media':MediaConfiguration(state).status(),'steps':[{'id':'installed','text':'商家版已安装，可直接描述目标。'},{'id':'official-cli','text':'需要店铺查询或操作时，Agent自动安装校验官方京麦CLI；离线任务不需要店铺登录。','action':None if client.ready() else 'doctor --install-cli'},{'id':'goal','text':'告诉我你想处理哪家店或哪份商品资料；需要新授权时，只请你用京麦App扫码并完成平台本人确认。'},{'id':'models','text':'生图和视频来源等待方案补充；已有素材、报表分析和业务准备可继续，不弹员工Key窗口。'}]}
 if command=='official-doc':return {'path':str(client.document(args.skill_id,args.reference,refresh=args.refresh)),'source':'official-policy-sha256-verified','execution':'read-rules-before-preparing-request'}
 if command=='shop-connect':return ops.connect(args.profile,args.shop_name,args.vender_id)
 if command=='auth-plan':return client.login_plan(args.profile,args.shop_name,args.vender_id)
 if command in ('auth-start','ensure-shop'):
  manager=AuthManager(state,client=client)
  method=manager.start if command=='auth-start' else manager.ensure_shop
  return method(args.shop_name,vender_id=args.vender_id,foreground=args.foreground)
 if command=='auth-restart':return AuthManager(state,client=client).restart(args.task_id,foreground=args.foreground)
 if command in ('auth-status','auth-observe','auth-cancel','auth-recover'):
  return getattr(AuthManager(state,client=client),command.removeprefix('auth-'))(args.task_id)
 if command=='task-plan':return ops.prepare(args.profile,_json_file(args.operation),_json_file(args.verification),precondition=_json_file(args.precondition),online_verification=_json_file(args.online_verification),result_verification=_json_file(args.result_verification))
 if command=='task-approve':return ops.approve(args.task_id,args.fingerprint,confirmed=args.confirm)
 if command=='task-execute':return ops.execute(args.task_id)
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
 if command=='prepare-listing':return prepare_listing(_json_file(args.product),args.source_root,args.output)
 if command=='package-snapshot':return package_snapshot(_json_file(args.snapshot),args.output)
 if command=='attach-video':return attach_video(args.manifest,args.video,args.cover,_json_file(args.review))
 raise SafetyError('unknown-command')

def main(argv=None):
 for stream in (sys.stdout,sys.stderr):
  if hasattr(stream,"reconfigure"):stream.reconfigure(encoding="utf-8",errors="backslashreplace")
 try:
  result=run(parser().parse_args(argv));print(json.dumps(public_result(redact(result)),ensure_ascii=False,allow_nan=False));return 0
 except (SafetyError,ValueError,OSError) as error:
  print(json.dumps({'status':'blocked','error':redact(str(error)),'paidCalls':0,'employeeFallback':False},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
