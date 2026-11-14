"""Build only audited distribution paths, with independent archive checksums."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.distribution import build_bundle,validate_archive
from heideng_merchant.safety import file_sha

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',default='dist');args=p.parse_args();root=Path(__file__).resolve().parents[1];version=(root/'VERSION').read_text().strip();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
 bundle=build_bundle(root,out/('heideng-ops-agent-merchant-'+version+'.zip'),version);manifest,_=validate_archive(bundle);sha=file_sha(bundle)
 (out/'SHA256SUMS').write_text(sha+'  '+bundle.name+'\n',encoding='ascii')
 print(json.dumps({'version':version,'archive':str(bundle),'sha256':sha,'fileCount':len(manifest['files'])}))
if __name__=='__main__':main()
