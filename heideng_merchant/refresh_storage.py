"""Merchant-owned shop state, preferences and write guards for shared POP tools."""
from .safety import file_sha, read_json, atomic_json
from .state import merchant_home
from .sku_image_edit import gallery_write_directory, product_image_lock


def configure_design(job, args):
    from . import image_design
    design = {}
    if args.approved_prompt_file:
        prompt = args.approved_prompt_file.read_bytes().decode('utf-8-sig')
        if not prompt.strip() or args.image_prompts_file:
            raise ValueError('商家原文与逐图提示词请选择一种')
        design.update(approvedPrompt=prompt, promptSource={'kind': 'merchant-brief', 'file': str(args.approved_prompt_file.resolve())})
    state = merchant_home()
    verified = image_design.identity(state, job['venderId'], job.get('shopId'), job['profile'])
    preference = image_design.load_design(state, verified) if verified else {}
    if args.reuse_approved_prompt:
        saved = preference.get('approvedPrompt') or {}
        if not saved or args.approved_prompt_file or args.image_prompts_file or args.use_host_design:
            raise ValueError('本店缺少已批准的提示词，或指定了冲突的设计来源')
        design.update(approvedPrompt=saved['text'], promptSource={k: v for k, v in saved.items() if k != 'text'})
    if (preference.get('preference') or {}).get('mode') == 'merchant-first' and not args.use_host_design:
        design['merchantBriefFirst'] = True
    return design
