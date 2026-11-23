"""The delivered expert navigates through its declared tools and ships usable domain notes."""
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import unittest
from zipfile import ZipFile

from scripts.build_workbuddy_expert import ROOT, SKILL, build


class ExpertGuidanceTests(unittest.TestCase):
    def test_source_navigation_keeps_the_merchant_workflows(self):
        notes = ROOT/'workbuddy-expert'/SKILL
        skill = (notes/'SKILL.md').read_text(encoding='utf-8')
        messages = [json.loads(text) for text in re.findall(r'`(\{"arguments":\[.*?\]\})`', skill)]
        self.assertIn({'arguments':['sample-context']}, messages)
        self.assertIn('merchant_command', skill)
        self.assertIn('远端京麦命令已关闭', skill)
        navigation = (notes/'references/experience-navigation.md').read_text(encoding='utf-8')
        links = re.findall(r'\[[^\]]+\]\(([^)]+)\)', navigation)
        content = '\n'.join((notes/'references'/link).read_text(encoding='utf-8') for link in links)
        for capability in ('audit-pop-coverage','repair-rejected','photo-listing','replace-sku-images',
                           'compare-evidence','comparison','video-binding','sample-context'):
            self.assertIn(capability, content)

    def test_package_uses_expert_notes_and_resolves_its_links(self):
        source = ROOT/'workbuddy-expert'/SKILL
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'expert.zip'
            build(output)
            with ZipFile(output) as archive:
                names = set(archive.namelist())
                supplied = {name for name in names if name.startswith(SKILL+'/references/')}
                self.assertSetEqual(supplied, {SKILL+'/'+file.relative_to(source).as_posix()
                                                for file in (source/'references').glob('*.md')})
                for name in sorted(supplied | {SKILL+'/SKILL.md','README.md','agents/heideng-merchant.md'}):
                    text = archive.read(name).decode('utf-8')
                    for previous in ('在本机安全窗口填写', '自行选择密码、短信或扫码',
                                     '认证魔方明确去京东商城App完成安全验证', 'scripts/with_image_key.py',
                                     'scripts/beta.py status'):
                        self.assertNotIn(previous, text, name)
                    for link in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
                        if '://' not in link and not link.startswith('#'):
                            self.assertIn((PurePosixPath(name).parent / link.split('#')[0]).as_posix(), names)
