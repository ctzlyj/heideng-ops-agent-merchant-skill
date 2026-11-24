"""Plan POP short-title submissions from validated original workbooks."""
import hashlib
import os
from pathlib import Path
import tempfile

from heideng_merchant.safety import file_sha, read_json, safe_join
from heideng_merchant.state import FileLock


ARCHIVE_MAX_ROWS = 10_000
IMPORT_MAX_ROWS = 5_000
IMPORT_MAX_BYTES = 5 * 1024 * 1024


def import_limits(row_count, byte_count, content_valid=True):
    reasons = []
    if row_count > IMPORT_MAX_ROWS:
        reasons.append('row-limit')
    if byte_count > IMPORT_MAX_BYTES:
        reasons.append('byte-limit')
    return {'validForSingleImport': bool(content_valid and not reasons),
            'importRowLimit': IMPORT_MAX_ROWS, 'importByteLimit': IMPORT_MAX_BYTES,
            'byteCount': byte_count, 'splitReasons': reasons}


class PriorImportReceipt(ValueError):
    def __init__(self, workbook_path, digest, receipt_path):
        self.workbook_path = workbook_path
        self.sha256 = digest
        self.receipt_path = receipt_path
        super().__init__(f'原表已有导入回执，请按原任务回查后再处理：{receipt_path}')


def _receipt_path(path, digest):
    return safe_join(path.parent,'.state/title-import-'+digest[:16]+'.json')


def _check_before_split(path, digest, *, source=False):
    receipt = _receipt_path(path,digest)
    if not receipt.exists():
        return
    saved = read_json(receipt)
    if not isinstance(saved,dict):
        raise ValueError(f'原导入回执无法核对，请保留原任务：{receipt}')
    if saved.get('kind') == 'short-title-import-batches':
        if saved.get('sha256') != digest:
            raise ValueError(f'拆批总账与原表的完整 SHA256 不一致，请核对原任务：{receipt}')
        if source:
            return  # The submitter resumes this aggregate with the original shop and child receipts.
        raise ValueError(f'原批次已有拆批总账，请按原文件和回执恢复：{path}，{receipt}')
    raise PriorImportReceipt(path, digest, receipt)


def _sized_chunks(rows, directories, agent):
    content = agent._short_title_workbook_bytes(rows)
    digest = hashlib.sha256(content).hexdigest()
    candidates = [safe_join(directory,digest[:20]+'.xlsx') for directory in directories]
    previous = [path for path in candidates if _receipt_path(path,digest).exists()]
    if len(previous) > 1:
        receipts = '、'.join(str(_receipt_path(path,digest)) for path in previous)
        raise ValueError(f'同一批短标题已有多份原回执，请先逐份核对：{receipts}')
    path = previous[0] if previous else candidates[0]
    if len(content) <= IMPORT_MAX_BYTES:
        yield path, digest, len(rows), content
        return
    _check_before_split(path, digest)
    if len(rows) == 1:
        raise ValueError(f'SKU {rows[0][0]} 单行按官方模板生成后有 {len(content)} 字节，'
                         f'超过每批 {IMPORT_MAX_BYTES} 字节；本次未提交。')
    middle = len(rows)//2
    yield from _sized_chunks(rows[:middle],directories,agent)
    yield from _sized_chunks(rows[middle:],directories,agent)


def _save_chunks(directory, generated):
    directory.mkdir(parents=True,exist_ok=True)
    with FileLock(directory/'prepare.lock'):
        for path,(digest,_) in generated.items():
            if path.exists() and file_sha(path) != digest:
                raise ValueError(f'原导入批次内容已改变，请保留文件并核对原回执：{path}')
        for path,(_,content) in generated.items():
            if path.exists():
                continue
            descriptor,name = tempfile.mkstemp(dir=directory,prefix='.preparing-')
            scratch = Path(name)
            try:
                with os.fdopen(descriptor,'wb') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(scratch,path)
            finally:
                scratch.unlink(missing_ok=True)


def _chunk_directories(source, output):
    # 0.4.24 passed the independent work item's lane as its output directory.
    # A repair mother workbook is itself inside that original batch directory.
    parent = source.parent
    if parent.name == 'title-import-chunks' and parent.parent.name == '.state':
        parent = parent.parent.parent
        if output == source.parent:
            output = parent
    roots = [output,parent]
    if parent.parent.name == '短标题独立交付':
        roots = [parent,output,parent.parent.parent]
    return [safe_join(root,'.state/title-import-chunks') for root in dict.fromkeys(roots)]


def save_import_workbook(path, content):
    """Freeze a generated repair workbook before it is used as an import source."""
    path = Path(path)
    _save_chunks(path.parent,{path:(hashlib.sha256(content).hexdigest(),content)})


def prepare_import_batches(paths, output_dir, *, agent=None):
    """Validate the entire delivery before exposing any batch for submission."""
    if agent is None:
        import jd_material_agent as agent
    output = Path(output_dir).resolve()
    batches, generated, seen_skus = [], {}, set()
    for item in paths:
        path = Path(item).resolve()
        report, rows = agent.inspect_short_title_workbook(path)
        if not report['contentValid']:
            invalid = report['invalidRows']
            detail = f"第 {invalid[0]['row']} 行：{', '.join(invalid[0]['reasons'])}" if invalid else '缺少商品行'
            raise ValueError(f'短标题原表内容不符合官方模板：{path}（{detail}）')
        for sku,_ in rows:
            if sku in seen_skus:
                raise ValueError(f'此次导入的多个来源包含重复 SKU {sku}，本次未提交。')
            seen_skus.add(sku)
        source = {'sourcePath':str(path), 'sourceSha256':report['sha256']}
        if report['validForSingleImport']:
            batches.append({**source, 'path':str(path), 'sha256':report['sha256'],
                            'rowCount':len(rows), 'byteCount':report['byteCount']})
            continue
        _check_before_split(path, report['sha256'],source=True)
        directories = _chunk_directories(path,output)
        for offset in range(0,len(rows),IMPORT_MAX_ROWS):
            for chunk,digest,count,content in _sized_chunks(rows[offset:offset+IMPORT_MAX_ROWS],directories,agent):
                contents = generated.setdefault(chunk.parent,{})
                if chunk in contents and contents[chunk][0] != digest:
                    raise ValueError(f'导入批次文件名发生冲突：{chunk}')
                contents[chunk] = (digest,content)
                batches.append({**source, 'path':str(chunk), 'sha256':digest,
                                'rowCount':count, 'byteCount':len(content)})
    for directory,contents in generated.items():
        _save_chunks(directory,contents)
    return batches
