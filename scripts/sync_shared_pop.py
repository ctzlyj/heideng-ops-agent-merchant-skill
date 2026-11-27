"""Maintainer tool. Copy the selected Git blobs and lock their exact origin."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from heideng_merchant.safety import safe_join
from heideng_merchant.upstream_updates import Reader

LOCK = ROOT / 'maintenance/shared-pop.json'


def write_json(path, value):
    current = path.read_bytes()
    data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    if b'\r\n' in current:
        data = data.replace(b'\n', b'\r\n')
    if current != data:
        path.write_bytes(data)


def mature_record(path, metadata, group, record):
    name = path.relative_to(ROOT).as_posix()
    if not name.startswith('mature/'):
        return
    component, rel = name.split('/', 2)[1:]
    prov_path = ROOT / 'mature' / component / 'provenance.json'
    if prov_path not in metadata:
        metadata[prov_path] = json.loads(prov_path.read_bytes())
    prov = metadata[prov_path]
    cross_repository = prov['repository'] != group['repository']
    if cross_repository and group['repository'] != 'ctzlyj/heideng-ops-agent-merchant-skill':
        raise ValueError(f'{name}: component repository mismatch')
    prov['files'][rel] = {
        'upstreamCommit': group['commit'], 'upstreamPath': record['source'],
        'upstreamSha256': record['sha256'], 'sha256': record['sha256'], 'adapted': False,
    }
    if cross_repository:
        prov['files'][rel]['upstreamRepository'] = group['repository']
    if name in group.get('entrypoints', []) and rel not in prov['entrypoints']:
        prov['entrypoints'].append(rel)


def sync(lock, group_name, source, commit):
    group = lock['groups'][group_name]
    origin = subprocess.check_output(['git', '-C', str(source), 'remote', 'get-url', 'origin'],
                                     text=True).strip().removesuffix('.git')
    repo = group['repository']
    if origin not in (f'https://github.com/{repo}', f'git@github.com:{repo}', f'ssh://git@github.com/{repo}'):
        raise ValueError(f'expected origin {repo}')
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('expected full Git commit')
    reader = Reader(source)
    if reader.run('cat-file', '-t', commit).strip() != b'commit':
        raise ValueError('expected a commit object')
    group['commit'] = commit
    metadata, contents = {}, {}
    package_path = ROOT / 'package-files.json'
    package = json.loads(package_path.read_bytes())
    for name, record in group['files'].items():
        path = safe_join(ROOT, name)
        contents[path] = data = reader.blob(commit, record['source'])
        record['sha256'] = hashlib.sha256(data).hexdigest()
        mature_record(path, metadata, group, record)
        if name.startswith('heideng_merchant/') and name not in package['files']:
            package['files'].append(name)
    for path, data in contents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    for path, value in metadata.items():
        write_json(path, value)
    write_json(package_path, package)
    write_json(LOCK, lock)


def verify(lock):
    seen = set()
    package = json.loads((ROOT / 'package-files.json').read_bytes())
    for group in lock['groups'].values():
        if not re.fullmatch('[0-9a-f]{40}', group['commit']):
            raise ValueError('invalid commit')
        metadata = {}
        for name, record in group['files'].items():
            if name in seen:
                raise ValueError(f'duplicate authority for {name}')
            seen.add(name)
            path = safe_join(ROOT, name)
            if name.startswith('heideng_merchant/') and name not in package['files']:
                raise ValueError(f'{name}: missing from source installation')
            if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError(f'{name}: differs from locked upstream')
            mature_record(path, metadata, group, record)
        for path, expected in metadata.items():
            if expected != json.loads(path.read_bytes()):
                raise ValueError(f'{path}: provenance disagrees with the shared source lock')
    return len(seen)


def main():
    lock = json.loads(LOCK.read_bytes())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=list(lock['groups']))
    parser.add_argument('--source', type=Path, help='local checkout of the authority repository')
    parser.add_argument('--commit', help='full upstream commit SHA')
    args = parser.parse_args()
    if any((args.group, args.source, args.commit)):
        if not all((args.group, args.source, args.commit)):
            parser.error('sync needs --group, --source and --commit')
        sync(lock, args.group, args.source, args.commit)
    print(f'{verify(lock)} shared files match their recorded Git source')


if __name__ == '__main__':
    main()
