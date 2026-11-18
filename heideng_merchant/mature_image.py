"""Only the mature SUFY client protocol; no company or personal credential lookup."""
from __future__ import annotations
import io, os, tempfile
from pathlib import Path
from PIL import Image
from . import lts4ai_client
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
    def __init__(self, key=None):
        self.client = lts4ai_client.SfImage2Client(key or merchant_key(), base_url=ENDPOINT, model=MODEL, retries=0)

    def edit(self, *, prompt, images, size='1024x1024'):
        references = lts4ai_client.validate_reference_images([Path(x) for x in images]) if images else []
        with tempfile.TemporaryDirectory(prefix='merchant-image-result-') as directory:
            try:
                if references:
                    result = self.client.edit(prompt, references, size, Path(directory))
                else:
                    result = self.client.generate(prompt, size, Path(directory))
            except lts4ai_client.SkillError as error:
                raise SafetyError(str(error).replace(self.client.api_key, '[REDACTED]')) from None
            with Image.open(result.path) as image:
                image.load()
                output = io.BytesIO()
                image.convert('RGB').save(output, 'JPEG', quality=95)
                return output.getvalue()
