"""Maintainer-only signed catalog publication; fixed Git blobs, not GitHub Releases."""
import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.update_catalog import sign, verify, digest
from heideng_merchant.distribution import build_bundle,validate_archive,version_key
from heideng_merchant.safety import read_json,atomic_json,SafetyError

REPOSITORY="ctzlyj/heideng-ops-agent-merchant-skill"

def dependency_fingerprint(files):
    names=sorted(n for n in files if "requirements" in n and n.endswith(".txt"))
    return hashlib.sha256(b"".join(n.encode()+b"\0"+files[n]+b"\0" for n in names)).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument("--project",type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument("--key",type=Path,default=Path.home()/".heideng-merchant-maintenance/signing/owner.pem")
    sub=p.add_subparsers(dest="command",required=True);sub.add_parser("init");sub.add_parser("renew")
    q=sub.add_parser("publish");q.add_argument("--notes",required=True);q.add_argument("--version")
    q=sub.add_parser("withdraw");q.add_argument("--release",required=True);q.add_argument("--reason",required=True)
    q=sub.add_parser("authorize-recovery");q.add_argument("--from-release",required=True);q.add_argument("--to-release",required=True)
    a=p.parse_args();r=a.project.resolve()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    if a.command=="init":
        if a.key.resolve().is_relative_to(r):raise SafetyError("signing-private-key-must-stay-outside-repository")
        a.key.parent.mkdir(parents=True,exist_ok=True)
        if not a.key.exists():
            key=Ed25519PrivateKey.generate();raw=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
            fd=os.open(a.key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,"wb") as f:f.write(raw)
        key=serialization.load_pem_private_key(a.key.read_bytes(),password=None);public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
        trust={"schemaVersion":1,"repository":REPOSITORY,"ref":"refs/heads/codex/merchant-foundation","keys":{"owner-2026":public},"bootstrap":"owner-authorized-private-repository-install; persisted-key-pin; signed-index-not-co-located-hash-authentication"}
        atomic_json(r/"updates/trust.json",trust);print(json.dumps({"status":"public-trust-configured","privateKeyDistributed":False}));return
    key=serialization.load_pem_private_key(a.key.read_bytes(),password=None);trust=read_json(r/"updates/trust.json");old=read_json(r/"updates/stable-index.json")
    payload=verify(old,trust,now=0) if old else {"schemaVersion":1,"repository":REPOSITORY,"sequence":0,"releases":[],"recoveries":[]}
    if a.command=="publish":
        if a.version:
            version_key(a.version)
            current=(r/"VERSION").read_text().strip()
            if version_key(a.version)<version_key(current):raise SafetyError("product-version-downgrade-refused")
            (r/"VERSION").write_text(a.version+"\n",encoding="utf-8")
            for path in [r/"SKILL.md",r/"heideng_merchant/__init__.py"]:
                import re
                text=path.read_text(encoding="utf-8")
                text=re.sub(r"(?m)^version: .*", "version: "+a.version,text) if path.name=="SKILL.md" else re.sub(r'(?m)^VERSION = ".*"', 'VERSION = "'+a.version+'"',text)
                path.write_text(text,encoding="utf-8",newline="\n")
            registry=read_json(r/"registry.json");registry["version"]=a.version;atomic_json(r/"registry.json",registry)
            readme=r/"README.md";text=readme.read_text(encoding="utf-8");text=re.sub(r"(?m)^# 黑灯运营智能体商家版 [0-9.]+", "# 黑灯运营智能体商家版 "+a.version,text);readme.write_text(text,encoding="utf-8",newline="\n")
        version=(r/"VERSION").read_text().strip();version_key(version)
        for p2 in (r/"mature").glob("*/provenance.json"):
            if read_json(p2).get("candidateOnly"):raise SafetyError("unadmitted-upstream-candidate")
        archive=build_bundle(r,r/"dist"/("heideng-ops-agent-merchant-"+version+".zip"),version);manifest,files=validate_archive(archive);sha=digest(archive)
        same=next((x for x in payload["releases"] if x["version"]==version),None)
        if same:
            if same["sha256"]!=sha:raise SafetyError("same-version-different-artifact")
            print(json.dumps({"status":"unchanged-fixed-release","release":same["id"]}));return
        path=r/"updates/artifacts"/("heideng-ops-agent-merchant-"+version+"-"+sha[:12]+".zip");path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and digest(path)!=sha:raise SafetyError("immutable-artifact-replacement-refused")
        path.write_bytes(archive.read_bytes());oid=subprocess.check_output(["git","-C",str(r),"hash-object",str(path)],text=True).strip()
        reg=read_json(r/"registry.json")
        release={"id":"merchant-"+version+"-"+sha[:12],"version":version,"status":"stable","gitBlob":oid,"downloadLocation":"https://api.github.com/repos/"+REPOSITORY+"/git/blobs/"+oid,"sizeBytes":path.stat().st_size,"sha256":sha,"manifestSha256":hashlib.sha256(files["package-manifest.json"]).hexdigest(),"compatibility":{"pythonMinimum":"3.11","platforms":["windows-x64","macos-arm64"],"hosts":["codex","joycode","claude","universal","explicit-skills-dir"],"hostRuntimeValidation":"folder-install-and-next-task-protocol-only-not-all-host-real-tests","loadedHostContent":"next-task-refresh-no-forced-restart"},"dependencyFingerprint":dependency_fingerprint(files),"officialCliUpgrade":"separate-original-official-installer","components":{p.parent.name:read_json(p)["upstreamCommit"] for p in (r/"mature").glob("*/provenance.json")},"notes":a.notes,"publishedAt":time.time(),"withdrawal":"signed-index-status-controls-future-installation"}
        payload["releases"].append(release)
    elif a.command=="withdraw":
        release=next(x for x in payload["releases"] if x["id"]==a.release);release.update(status="withdrawn",withdrawalReason=a.reason)
    elif a.command=="authorize-recovery":
        before=next(x for x in payload["releases"] if x["id"]==a.from_release);after=next(x for x in payload["releases"] if x["id"]==a.to_release)
        if after["status"]!="stable":raise SafetyError("recovery-target-not-stable")
        payload["recoveries"].append({"fromSha256":before["sha256"],"toSha256":after["sha256"],"approval":"maintenance-signed-explicit-recovery"})
    payload.update(sequence=payload["sequence"]+1,issuedAt=time.time(),expiresAt=time.time()+365*86400)
    atomic_json(r/"updates/stable-index.json",sign(payload,key,"owner-2026"));print(json.dumps({"status":"prepared-fixed-artifact-and-signed-index-not-yet-pushed","sequence":payload["sequence"]}))

if __name__=="__main__":main()
