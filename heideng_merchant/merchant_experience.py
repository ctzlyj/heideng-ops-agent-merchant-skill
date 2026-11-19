"""Small read-only projections of existing business receipts, not a scheduler."""
from __future__ import annotations


# These classify returned receipts; they do not schedule or transition business tasks.
_DONE = {'completed','completed-materials','verified','approved','import-completed','verified-apply'}
_EMPTY = {'no-work','no-rejections','no-cutout-slots','no-op','no-titles','no-external-images','not-requested'}
_LOCAL = {'planned','planned-existing','generated-local','prepared'}
_COMPONENTS = ('shortTitleDelivery','productAttributes','rejectedRepairs','externalImages')


def _count(value):
    if isinstance(value, (list, tuple, dict)):return len(value)
    return max(0, value) if isinstance(value, int) else 0


def _receipt_facts(value):
    status=str(value.get('status') or '')
    rows=value.get('rows') or []
    errors=value.get('errors') or []
    row_states=[str(row.get('status') or '') for row in [*rows, *errors] if isinstance(row,dict)]
    failed=max(_count(value.get('failedCount')), _count(value.get('failed_spus')), _count(errors),
               _count(value.get('platformFailedRows')), _count(value.get('failedRows')),
               row_states.count('rejected')+row_states.count('blocked')+row_states.count('unknown'))
    pending=max(_count(value.get('pendingReviewCount')), _count(value.get('pending_spus')), row_states.count('pending'))
    unknown=('unknown' in status or any('unknown' in item for item in row_states))
    blocked=(_count(value.get('imageReviewRequired'))>0 or _count(value.get('remainingImageSlotCount'))>0 or failed>0 or any(word in status for word in ('incomplete','with-failures','blocked','partial-titles','failed'))
             or value.get('allVerified') is False or bool(value.get('blocked')))
    waiting=pending>0 or ('review' in status and value.get('allApproved') is not True)
    submitted=status.startswith(('submitted','jingmai-submitted','repairs-submitted')) or status=='appeal-only'
    done=(status in _DONE or status in _EMPTY or value.get('allVerified') is True or value.get('allApproved') is True)
    if unknown:phase='needs-reconciliation'
    elif blocked:phase='needs-agent-action'
    elif waiting:phase='waiting-review'
    elif done:phase='completed'
    elif submitted:phase='submitted'
    elif status in _LOCAL:phase='prepared'
    else:phase='needs-agent-action'  # A returned command is not proof of a running process.
    return {'status':status,'phase':phase,'failedCount':failed,'pendingReviewCount':pending}


def task_summary(payload):
    value=payload if isinstance(payload,dict) else {}
    merchant_action=value.get('needsMerchantAction') is True or any(isinstance(value.get(k),dict) and value[k].get('needsMerchantAction') is True for k in _COMPONENTS)
    if any(key in value for key in ('reconciledUploads','reconciledBindings','unresolvedUploads','unresolvedBindings')):
        uploads=value.get('reconciledUploads') or [];bindings=value.get('reconciledBindings') or []
        unresolved=_count(value.get('unresolvedUploads'))+_count(value.get('unresolvedBindings'))
        pending=sum(1 for item in bindings if item.get('status')=='pending')
        phase='needs-reconciliation' if unresolved else 'waiting-review' if pending else 'completed'
        completed=len(uploads)+len(bindings);total=completed+unresolved;failed=unresolved;components={}
        message=f'原任务已对账，仍有{unresolved}项结果需要核对。' if unresolved else f'原任务已对账，{pending}条绑定等待平台审核。' if pending else '原任务回执已对账，没有未确认的上传或绑定。'
    else:
        batches=value.get('batches') or []
        total=_count(value.get('spuCount')) or sum(_count(b.get('spuCount')) for b in batches) or _count(value.get('rows'))+_count(value.get('errors'))
        completed=_count(value.get('completedCount')) or sum(_count(b.get('completedSpus')) for b in batches)
        own=_receipt_facts(value)
        components={key:_receipt_facts(value[key]) for key in _COMPONENTS if isinstance(value.get(key),dict) and value[key].get('status')!='not-requested'}
        # Batch failures may not be reflected by a top-level status. Do not lose upload/reference/finalization failures.
        failed=max(own['failedCount'],sum(max(_count(b.get('failedSpus')), _count((b.get('binding') or {}).get('failed_spus')),
                   _count((b.get('upload') or {}).get('failed_files')), _count(b.get('referenceFailures')),
                   _count((b.get('finalization') or {}).get('failedSpus'))) for b in batches))
        pending=max(own['pendingReviewCount'],sum(_count((b.get('binding') or {}).get('pending_spus')) for b in batches))
        phases=[own['phase'],*(item['phase'] for item in components.values())]
        failed+=sum(item['failedCount'] for item in components.values())
        pending+=sum(item['pendingReviewCount'] for item in components.values())
        if 'needs-reconciliation' in phases:phase='needs-reconciliation'
        elif merchant_action:phase='needs-merchant-action'
        elif failed or 'needs-agent-action' in phases:phase='needs-agent-action'
        elif pending or 'waiting-review' in phases:phase='waiting-review'
        elif 'submitted' in phases:phase='submitted'
        elif 'prepared' in phases:phase='prepared'
        else:phase='completed'
        message={'needs-reconciliation':'部分操作结果尚未确认，已保留原任务和回执。',
                 'needs-merchant-action':'需要本人登录验证或商家确认新的范围/费用；其余结果已保留。',
                 'needs-agent-action':'执行已返回，仍有失败、缺项或未识别的回执；由Agent核对并处理剩余范围。',
                 'waiting-review':'已提交，正在等待平台审核。',
                 'submitted':'已提交，尚待平台核验；不代表业务已生效。',
                 'prepared':'本次准备已完成，尚未完成业务提交与核验。',
                 'completed':'本次任务已完成。' if value.get('status') not in _EMPTY else '本次范围没有需要执行的项目。'}[phase]
    action={'needs-reconciliation':'从原任务读取回执并核对，不要盲目重试。',
            'needs-merchant-action':'请完成当前本人步骤或范围/费用决策；不重新提交已完成部分。',
            'needs-agent-action':'查看分项结果文件；Agent先诊断，仅补剩余范围，必要决策才询问商家。',
            'waiting-review':'可以离开；稍后从原任务恢复查看，不会重复提交。',
            'submitted':'可以离开；从原任务核对平台结果，不重复提交。',
            'prepared':'沿用本次计划与输入，由Agent继续已授权范围；新费用另行确认。',
            'completed':'查看交付结果。'}[phase]
    if phase=='needs-agent-action' and _count(value.get('imageReviewRequired'))>0:
        message='先由Agent查看驳回图、核实文字来源，再按实际原因重新设计本任务提示词；不是要求商家手工修图。'
        action='读取imageReviewRequired和可靠参考图；额外生成文字按原任务/剩余预算修复，商品真实印刷误驳回走申诉。'
    if phase=='needs-merchant-action' and value.get('manualAppealRequired'):
        message='原申诉清单已生成但尚未提交；请按审核原因处理，不重复付费生图。'
        action='按原审核原因处理申诉；Agent继续核对其余剩余项，不重复提交或扩大付费范围。'
    needs=phase in ('needs-agent-action','needs-reconciliation') or _count(value.get('remainingImageSlotCount'))>0
    return {'phase':phase,'message':message,'nextAction':action,'completed':phase=='completed','canLeave':True,
            'completedCount':completed,'totalCount':total,'pendingReviewCount':pending,'failedCount':failed,
            'needsUserAction':merchant_action,'needsAgentAction':needs,'needsMerchantAction':merchant_action,
            'retryAllowed':False,'components':components,'resultFile':value.get('resultFile')}


def merchant_status(version):
    return {'version':version,'message':'黑灯商家版已安装，可以直接描述店铺任务。','firstAction':'已有店铺授权会直接复用；新店会在需要时打开登录页。',
            'paidOrWriteActions':'未自动执行','merchantLiveVerified':False}


def error_summary(error):
    from .safety import redact
    text=str(error).lower()
    if any(word in text for word in ('unknown','result_unknown','uncertain')):
        kind='needs-reconciliation';message='操作结果未确认，请从原任务核对，不重复提交。'
    elif any(word in text for word in ('dependency','runtime','python','module','importerror')):
        kind='environment-preparation';message='当前运行环境尚未就绪，Agent应先修复依赖再继续原任务。'
        if any(word in text for word in ('network','timeout','unreachable')):
            kind='retryable-environment';message='当前环境或网络暂不可用，Agent先诊断，再从原任务恢复。'
    elif any(word in text for word in ('network','timeout','unavailable','unreachable')):
        kind='retryable-environment';message='当前环境暂时不可用，Agent先诊断，再从原任务恢复。'
    elif any(word in text for word in ('login_required','needs_auth','扫码','验证码','captcha','confirmation_scope','budget','费用','授权范围')):
        kind='merchant-decision';message='需要商家完成本人登录验证或确认新增范围/费用；原任务已保留。'
    else:
        kind='agent-diagnosis';message='任务尚未完成，Agent应查看原任务状态与脱敏技术原因，先诊断处理。'
    return {'kind':kind,'message':message,'needsMerchantAction':kind=='merchant-decision',
            'needsAgentAction':kind!='merchant-decision','retryAllowed':False,'technicalReason':redact(str(error))}
