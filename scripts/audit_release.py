"""Audit release contents, not user credential directories."""
import argparse,json,re,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.distribution import validate_archive
from heideng_merchant.safety import SafetyError

def audit(archive):
 manifest,files=validate_archive(archive);issues=[]
 for name,raw in files.items():
  if Path(name).suffix.lower() not in ('.py','.md','.json','.mjs','.js','.cjs','.html','.txt','.sh','.ps1') and Path(name).name!='LICENSE':continue
  text=raw.decode('utf-8-sig')
  if re.search(r'caotong\.888|[CD]:[\\/]Users[\\/]|[CD]:[\\/]UserData[\\/]',text):issues.append({'file':name,'issue':'personal-path'})
  if re.search(r'gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9_-]{20,}',text):issues.append({'file':name,'issue':'credential-pattern'})
 skill=files['SKILL.md'].decode('utf-8-sig')
 for ref in set(re.findall(r'(?<![a-zA-Z0-9_/-])(?:mature/[a-zA-Z0-9_-]+/)?references/[a-zA-Z0-9_-]+\.md',skill)):
  if ref not in files:issues.append({'file':'SKILL.md','issue':'missing-reference','reference':ref})
 if issues:raise SafetyError(json.dumps({'releaseAudit':'failed','issues':issues}))
 return {'releaseAudit':'passed','version':manifest['version'],'fileCount':len(files),'personalPaths':0,'credentialPatterns':0,'unknownFiles':0,'scope':'audited-release-only-not-third-party-runtime-or-live-shop'}

def main():
 p=argparse.ArgumentParser();p.add_argument('archive');args=p.parse_args()
 print(json.dumps(audit(Path(args.archive))))
if __name__=='__main__':main()
