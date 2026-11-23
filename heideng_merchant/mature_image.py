"""Only the mature SUFY client protocol; no company or personal credential lookup."""
from __future__ import annotations
import io, os, re, tempfile
from pathlib import Path
from PIL import Image
from . import lts4ai_client
from .image_models import MODELS
from .safety import SafetyError

ENDPOINT = 'https://api.lts4ai.com/v1'
MODEL = 'gpt-image-2.5'

def merchant_key():
    value = os.environ.get('HEIDENG_MERCHANT_LTS4AI_API_KEY', '').strip()
    if not value and os.environ.get('HEIDENG_MERCHANT_HOME'):
        # Only the isolated merchant namespace; never discover a personal/company secret store.
        from .merchant_key_store import read_key
        value=(read_key(Path(os.environ['HEIDENG_MERCHANT_HOME'])) or '').strip()
    if not value:
        raise SafetyError('merchant-lts4ai-key-required：实际生图需要商家自己的Key；请通过 scripts/with_image_key.py 安全配置，不粘贴到聊天。')
    return value

class MerchantImageClient:
    def __init__(self, key=None, model=MODEL):
        _check_image_access()
        if model not in MODELS:
            raise SafetyError('merchant-image-model-not-configured')
        self.client = lts4ai_client.SfImage2Client(key or merchant_key(), base_url=ENDPOINT, model=model, retries=0)

    def edit(self, *, prompt, images, size='1024x1024'):
        _check_image_access()
        references = lts4ai_client.validate_reference_images([Path(x) for x in images]) if images else []
        with tempfile.TemporaryDirectory(prefix='merchant-image-result-') as directory:
            try:
                if references:
                    result = self.client.edit(prompt, references, size, Path(directory))
                else:
                    result = self.client.generate(prompt, size, Path(directory))
            except lts4ai_client.SkillError as error:
                # Only expose the response category; gateway diagnostic bodies can
                # contain account, routing and billing details beyond the merchant quote.
                message = str(error)
                status = re.search(r'\(HTTP (\d{3})\)',message)
                if message.startswith('LTS4AI token quota is not enough'):
                    public = 'LTS4AI 积分额度不足'
                elif message.startswith('LTS4AI authentication failed'):
                    public = 'LTS4AI Key 验证失败'
                elif message.startswith('LTS4AI rate limit'):
                    public = 'LTS4AI 请求受限，请核对额度和原任务'
                else:
                    public = 'LTS4AI 未交付可核验的图片，请核对原请求'
                if status:
                    public += ' (HTTP '+status[1]+')'
                if lts4ai_client.UNKNOWN_RESULT in message:
                    public += ' '+lts4ai_client.UNKNOWN_RESULT
                raise SafetyError(public) from None
            with Image.open(result.path) as image:
                image.load()
                output = io.BytesIO()
                image.convert('RGB').save(output, 'JPEG', quality=95)
                return output.getvalue()


def _check_image_access():
    if os.environ.get('HEIDENG_MERCHANT_BETA_IMAGE_BLOCKED') in ('quota-exhausted', 'unbounded-key'):
        raise SafetyError('内测 Key 的生图额度已用尽或未设置上限，请核对 LTS4AI 额度')
