"""Static local preflight: no API request, browser, login, shop write or generation."""
import importlib, json, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from heideng_merchant.safety import SafetyError
from heideng_merchant.mature_runtime import install_network_guard
install_network_guard()

class SafeParser:
    """Use the original parser but turn normal --help/errors into a safe static diagnostic."""
    def __init__(self, parser):self.parser=parser
    def parse_args(self, arguments):
        class Refusal(Exception):pass
        def stop(status=0,message=None):raise Refusal(status,message)
        import unittest.mock
        with unittest.mock.patch.object(self.parser,'exit',side_effect=stop):
            try:return self.parser.parse_args(arguments)
            except Refusal as error:
                if error.args and error.args[0]==0:return None
                raise ValueError('命令参数校验未通过') from None


def main():
    capability,path,*arguments=sys.argv[1:]
    try:
        for module in ('httpx','requests','openpyxl','PIL'):importlib.import_module(module)
        if capability in ('materials','short-title'):
            sys.path.insert(0,str(Path(path).parent));import jd_material_agent as a
            args=SafeParser(a.build_parser()).parse_args(arguments)
            if args is None:print(json.dumps({'status':'help-or-command-usage','businessExecuted':False}));return 2  # Validate original command contract before key input.
            if args.command in ('auto-maintain','generate-auto-maintain'):
                output=Path(args.output_dir)
                if not (output/a.AUTO_MAINTAIN_PLAN_NAME).is_file():raise ValueError('先完成只读 plan-auto-maintain 并由宿主确认范围/费用，不先录Key')
                frozen=json.loads((output/a.AUTO_MAINTAIN_PLAN_NAME).read_text(encoding='utf-8'))
                prepared,_,_,_=a.load_pop_auto_maintain_plan(output,frozen.get('shopIdentity') or {},getattr(args,'target_spu_id',None))
                if getattr(args,'expected_shop_name',None) and (frozen.get('shopIdentity') or {}).get('shopName') != args.expected_shop_name:raise ValueError('店名与冻结计划不一致')
                text=a.load_agent_text(args.agent_text_file) if args.agent_text_file else {'selling_points':{},'short_titles':{}}
                text=a._validate_agent_text_scope(text,prepared)
                # Existing original task text remains reusable. Report exact missing SKU IDs, not all 299 rows.
                missing=[]
                for index,rows in a.frozen_scope_batches(prepared,output):
                    state=a._load_state(output/f'批次{index:03d}'/'.state/task.json')
                    for job in a._subset_prepared(prepared,rows).jobs:
                        item=state.get('jobs',{}).get(job.spu_id,{})
                        missing.extend(sku for sku in job.short_title_sku_ids if sku not in text['short_titles'] and not a.valid_short_title((item.get('short_titles') or {}).get(sku)))
                        if job.needs_selling_points and not item.get('selling_points') and job.spu_id not in text['selling_points']:raise ValueError('宿主需先补冻结计划内卖点：SPU '+job.spu_id)
                if missing:raise ValueError('宿主需先补实际缺失短标题SKU：'+','.join(missing[:30])+f'（共{len(missing)}）')
                if args.command=='auto-maintain' and args.upload_mode!='browser' and any(a._has_material_work(job) for job in prepared.jobs):
                    a.JdoClient(args.profile,output/'.state/jdo-runtime').check_bridge()
        print(json.dumps({'status':'ready','businessExecuted':False,'paidCalls':False}));return 0
    except (ImportError,OSError,ValueError,RuntimeError) as error:
        # No HTTP is issued, so these are definitely local pre-submit failures, not unknown writes.
        print(json.dumps({'status':'pre-submit-blocked','reason':str(error)[:400],'businessExecuted':False,'paidCalls':False},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
