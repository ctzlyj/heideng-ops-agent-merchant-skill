"""Build and reopen an editable POP price label from generated PNG pixels and a synthetic field spec."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib


def synthetic_png(path):
    def chunk(tag, data):
        return struct.pack('>I',len(data)) + tag + data + struct.pack('>I',zlib.crc32(tag+data))
    top = bytes([0]) + bytes([245,245,245,255])*800
    bottom = bytes([30,90,150,255])*800
    rows=[]
    for y in range(600,800):
        row=bytearray(bottom)
        for left,right,low,high in [(35,90,630,655),(110,175,630,655),(430,490,655,690)]:
            if low<=y<high:
                row[left*4:right*4]=bytes([255,230,20,255])*(right-left)
        rows.append(b'\0'+row)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR',struct.pack('>IIBBBBB',800,800,8,6,0,0,0))
                     + chunk(b'IDAT',zlib.compress(top*600+b''.join(rows))) + chunk(b'IEND',b''))


def run_contract(state, *, merchant=None, prefix=None):
    env=dict(os.environ, HEIDENG_MERCHANT_HOME=str(state), PYTHONUTF8='1')
    def run(argv, expected=0):
        result=subprocess.run(list(map(str, argv)), env=env, encoding='utf-8',errors='replace',
                              capture_output=True, timeout=210)
        assert result.returncode==expected, (result.returncode,result.stdout[-700:],result.stderr[-900:])
        return result.stdout
    if merchant:
        skills=state/'skills'
        run([sys.executable,merchant/'install.py','--state',state,'--skills-dir',skills,
             '--offline','--no-auto-update'])
        entry=skills/'heideng-ops-agent-merchant/scripts/merchant.py'
        prefix=[sys.executable,entry,'--state',state,'run','psd-template','--']
    prefix=prefix or ['node',Path(__file__).resolve().parents[1]/'scripts/psd_template.cjs']
    first=json.loads(run([*prefix,'status']))
    assert first=={'ready':False,'optional':True,'platformWrites':0}
    assert not (state/'optional-runtimes').exists()
    source,spec,out=state/'source.png',state/'spec.json',state/'template'
    synthetic_png(source)
    field={'bounds':[20,620,300,665],'sampleText':'SAMPLE',
           'font':{'name':'ArialMT','fontSize':28,'color':[20,20,20]}}
    spec.write_text(json.dumps({'schemaVersion':1,'templateId':'fixture','displayName':'Synthetic label',
        'dynamicFields':[{**field,'jdColumn':'文案1','businessRole':'campaign'}],
        'automaticPriceLayer':{**field,'bounds':[410,640,680,702],'sampleText':'19.90'}}),encoding='utf-8')
    receipt=json.loads(run([*prefix,'build','--source',source,'--spec',spec,'--output-dir',out]))
    manifest_path=Path(receipt['manifestPath'])
    manifest=json.loads(manifest_path.read_text(encoding='utf8'))
    assert manifest['automaticPriceLayer']['jdField']=='价格'
    assert manifest['jdExcelColumns']==['SKUID','文案1']
    assert receipt['localStatus']=='passed' and receipt['platformWrites']==0
    assert receipt['jdUploadStatus']=='pending' and receipt['jdReady'] is False
    assert receipt['officialTextEngine'] is False
    check=json.loads(run([*prefix,'verify','--manifest',manifest_path]))
    assert check['valid'] and check['width']==check['height']==800
    assert [(l['name'],l['type']) for l in check['layers']]==[
        ('背景装饰','pixel'),('文案1','text'),('自动价格','text')]
    assert check['jdUploadStatus']=='pending' and all(row['valid'] for row in check['fileChecks'])
    manifest['jdExcelColumns'].append('价格')
    manifest_path.write_text(json.dumps(manifest),encoding='utf8')
    invalid=json.loads(run([*prefix,'verify','--manifest',manifest_path],expected=2))
    assert not invalid['valid'] and not invalid['manifestChecks']['jdColumns']
    assert not invalid['jdReady']
    print(json.dumps({'layers':3,'priceLayer':'editable','invalidPriceColumn':'rejected',
                      'localStatus':receipt['localStatus'],'jdUploadStatus':'pending','platformWrites':0}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--merchant-root',type=Path)
    parser.add_argument('--entry-json',type=json.loads)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        prefix=[s.replace('{state}',tmp) for s in args.entry_json] if args.entry_json else None
        run_contract(Path(tmp),merchant=args.merchant_root,prefix=prefix)
