"""Bind commercial image work to the host's design and the original source bytes."""
from hashlib import sha256
import json
from pathlib import Path

from .image_budget import reserve_request, validate_approval
from .safety import atomic_json


def host_prompt(prompts, image_id):
    prompt = prompts.get(image_id) if isinstance(prompts, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f'宿主须根据真实商品与本次目标设计图片 {image_id} 的完整提示词')
    return prompt.strip()


class CreativeOrder:
    """Write the exact quote even if approval is still pending. Cached work costs zero."""

    def __init__(self, directory, context, designs, pending, approval_file, *, reused=None):
        self.directory = Path(directory)
        self.units = sorted(designs)
        sources = {key: row['sourceSha256'] for key, row in designs.items()}
        digest = sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
        self.scope = {**context, 'model': 'gpt-image-2.5', 'sourceSetSha256': digest}
        self.quote = {
            'scope': self.scope, 'units': self.units, 'pendingUnits': sorted(pending), 'canSelectUnits': True,
            'newImageCount': len(pending), 'suggestedMaxRequests': len(pending),
            'actualAmount': None, 'designs': designs, 'reusedSources': reused or {},
        }
        atomic_json(self.directory / 'image-quote.json', self.quote)
        from .commercial_tasks import register
        register('creative', self.directory, context.get('shop') or {}, context.get('kind'))
        self.approval_file = Path(approval_file) if approval_file else self.directory / 'fee-approval.json'

    def check(self):
        if not self.approval_file.is_file():
            raise ValueError('生图报价已保存到 image-quote.json，取得本次费用批准后传入 --fee-approval-file')
        self.approval = json.loads(self.approval_file.read_text(encoding='utf-8-sig'))
        units = self.approval.get('units')
        if not isinstance(units, list) or not set(units).issubset(self.units):
            raise ValueError('批准的图位不属于本任务')
        validate_approval(self.approval, scope=self.scope, units=units)
        self.selected = [key for key in self.quote['pendingUnits'] if key in units]
        self.deferred = [key for key in self.quote['pendingUnits'] if key not in units]
        if self.approval['maxRequests'] < len(self.selected):
            raise ValueError('计划新增图片数超过批准请求数，请缩小范围并核对报价')
        self.quote.update(selectedUnits=self.selected, deferredUnits=self.deferred)
        atomic_json(self.directory / 'image-quote.json', self.quote)

    def reserve(self, key):
        return reserve_request(self.directory, self.approval, scope=self.scope, units=self.approval['units'], request_id=key)
