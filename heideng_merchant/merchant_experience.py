"""Small read-only projections of existing business receipts, not a scheduler."""
from __future__ import annotations


def task_summary(payload):
    value=payload if isinstance(payload,dict) else {}
    if any(key in value for key in ('reconciledUploads','reconciledBindings','unresolvedUploads','unresolvedBindings')):
        reconciled_uploads=value.get('reconciledUploads') or []
        reconciled_bindings=value.get('reconciledBindings') or []
        unresolved_uploads=value.get('unresolvedUploads') or []
        unresolved_bindings=value.get('unresolvedBindings') or []
        unresolved=len(unresolved_uploads)+len(unresolved_bindings)
        pending=sum(1 for item in reconciled_bindings if item.get('status')=='pending')
        if unresolved:
            phase='needs-reconciliation';message=f'原任务已对账，仍有{unresolved}项结果需要核对。';action='查看未决项和原回执，只处理未决范围，不重复提交。';completed=False;can_leave=True;needs_action=True
        elif pending:
            phase='waiting-review';message=f'原任务已对账，{pending}条绑定正在等待平台审核。';action='可以离开；稍后从原任务恢复查看，不会重复提交。';completed=False;can_leave=True;needs_action=False
        else:
            phase='completed';message='原任务回执已对账，没有未确认的上传或绑定。';action='查看对账结果并继续剩余业务。';completed=True;can_leave=True;needs_action=False
        return {'phase':phase,'message':message,'nextAction':action,'completed':completed,'canLeave':can_leave,
                'completedCount':len(reconciled_uploads)+len(reconciled_bindings),'totalCount':len(reconciled_uploads)+len(reconciled_bindings)+unresolved,
                'pendingReviewCount':pending,'failedCount':unresolved,'needsUserAction':needs_action,'retryAllowed':False,'resultFile':value.get('resultFile')}
    batches=value.get('batches') or []
    total=value.get('spuCount') or sum(int(b.get('spuCount') or 0) for b in batches)
    completed=sum(int(b.get('completedSpus') or 0) for b in batches)
    pending=sum(int((b.get('binding') or {}).get('pending_spus') or 0) for b in batches)
    failed=sum(int((b.get('binding') or {}).get('failed_spus') or 0) for b in batches)
    status=str(value.get('status') or '')
    unknown='unknown' in status or status=='paused-unknown-write'
    needs=bool(failed or any(b.get('failedSpus') or b.get('referenceFailures') for b in batches))
    waiting=bool(pending or 'waiting-review' in status or 'awaiting-review' in status)
    finished=status in ('completed','completed-materials','verified') and not needs
    if unknown:
        phase='needs-reconciliation';message='部分操作结果尚未确认，已保留原任务和回执。';action='从原任务读取回执并核对，不要盲目重试。';retry=False
    elif waiting:
        phase='waiting-review';message=f'已提交，正在等待平台审核（{pending or "部分"}个商品）。';action='可以离开；稍后从原任务恢复查看，不会重复提交。';retry=False
    elif needs:
        phase='needs-user-action';message=f'已完成部分任务，仍有失败或需处理的项目。';action='查看结果文件，仅处理失败范围，已完成部分不重做。';retry=False
    elif finished:
        phase='completed';message='本次任务已完成。';action='查看交付结果。';retry=False
    else:
        phase='in-progress';message=f'任务正在处理，已完成{completed}/{total}个商品。';action='可以继续等待或离开；从原任务恢复。';retry=True
    return {'phase':phase,'message':message,'nextAction':action,'completed':finished,'canLeave':waiting or finished,
            'completedCount':completed,'totalCount':total,'pendingReviewCount':pending,'failedCount':failed,
            'needsUserAction':needs or unknown,'retryAllowed':retry,'resultFile':value.get('resultFile')}


def merchant_status(version):
    return {'version':version,'message':'黑灯商家版已安装，可以直接描述店铺任务。','firstAction':'已有店铺授权会直接复用；新店会在需要时打开登录页。',
            'paidOrWriteActions':'未自动执行','merchantLiveVerified':False}


def error_summary(error):
    text=str(error)
    if 'unknown' in text or 'result_unknown' in text:return {'kind':'needs-reconciliation','message':'操作结果未确认，请从原任务核对，不重复提交。'}
    if any(x in text for x in ('network','timeout','unavailable','unreachable')):return {'kind':'retryable-environment','message':'当前环境暂时不可用，可从原任务恢复。'}
    if any(x in text for x in ('dependency','runtime','python','module')):return {'kind':'environment-preparation','message':'运行环境尚未准备好，请先补齐依赖再执行。'}
    return {'kind':'action-required','message':'任务需要进一步处理，请查看原任务状态和结果文件。'}
