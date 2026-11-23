"""Build one local WorkBuddy expert from the audited merchant release."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from heideng_merchant.distribution import build_bundle, validate_archive
from heideng_merchant.safety import file_sha
from scripts.audit_release import audit

SKILL = 'skills/heideng-merchant-beta'
EXPERT = 'heideng-merchant'


def read_invites(path):
    if path is None:
        return []
    data = json.loads(Path(path).read_bytes())
    if not isinstance(data, list) or not data or not all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) for v in data):
        raise ValueError('需要非空的 SHA-256 指纹 JSON 数组，原始 Key 不能用于打包。')
    return sorted(set(data))


def build(output, invites=None, email='preview@example.invalid'):
    output = Path(output)
    if output.suffix.lower() != '.zip' or (invites and output.resolve() == Path(invites).resolve()):
        raise ValueError('输出需要单独的 .zip 文件')
    if invites and (not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or email.endswith('.invalid')):
        raise ValueError('分发候选需要真实的发布联系人邮箱')
    version = (ROOT/'VERSION').read_text().strip()
    with tempfile.TemporaryDirectory(prefix='heideng-workbuddy-build-') as tmp:
        archive = build_bundle(ROOT, Path(tmp)/'core.zip', version)
        audit(archive)
        manifest, files = validate_archive(archive)
        if manifest['version'] != version:
            raise ValueError('商家包版本不一致')
        config = json.loads((ROOT/'workbuddy-expert/plugin.json').read_text(encoding='utf-8'))
        config['author']['email'] = email
        config['version'] = version
        digests = read_invites(invites)
        # WorkBuddy sees one Skill. Ship its audited runtime as one immutable payload
        # so the host cannot accidentally register the core's standalone SKILL.md.
        files = {f'{SKILL}/{n}':data for n,data in files.items() if n.startswith('references/')}
        files[f'{SKILL}/resources/merchant.zip'] = archive.read_bytes()
        for name in ('avatars/heideng.png', 'agents/heideng-merchant.md', 'README.md',
                     f'{SKILL}/scripts/beta.py', f'{SKILL}/SKILL.md'):
            files[name] = (ROOT/'workbuddy-expert'/name).read_bytes()
        files['.codebuddy-plugin/plugin.json'] = json.dumps(config,ensure_ascii=False,indent=2).encode()
        files[f'{SKILL}/expert-distribution.json'] = json.dumps(
            {'version':version,'coreSha256':file_sha(archive),'inviteDigests':digests}, separators=(',',':')).encode()
        output.parent.mkdir(parents=True,exist_ok=True)
        fd, target = tempfile.mkstemp(prefix='.expert-',suffix='.zip',dir=output.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(target,'w') as z:
                for name, data in sorted(files.items()):
                    info = zipfile.ZipInfo(name, (2026,1,1,0,0,0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(info, data)
            os.replace(target,output)
        finally:
            Path(target).unlink(missing_ok=True)
    return {'expert':EXPERT,'version':version,'file':str(output),'sha256':file_sha(output),
            'invitedKeys':len(digests),'mode':'invite-only-candidate' if digests else 'preview-no-access'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='本地构建 WorkBuddy 单专家，无自动上传。')
    access = parser.add_mutually_exclusive_group(required=True)
    access.add_argument('--preview',action='store_true',help='没有内测资格的开发预览')
    access.add_argument('--invite-digests',type=Path,help='运营方在仓库外提供的一批专用 Key 的 SHA-256 指纹数组')
    parser.add_argument('--publisher-email',default='preview@example.invalid')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output,args.invite_digests,args.publisher_email),ensure_ascii=False))
