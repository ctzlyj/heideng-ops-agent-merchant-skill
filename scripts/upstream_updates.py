"""Maintainer-only explicit discovery/candidate/admission. Does not run business tools."""
import argparse, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from heideng_merchant.upstream_updates import candidate, fetch_component
from heideng_merchant.safety import read_json, atomic_json, SafetyError, safe_join
from heideng_merchant.distribution import source_files


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--project",type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument("--state",type=Path,default=Path.home()/".heideng-merchant-maintenance")
    sub=p.add_subparsers(dest="command",required=True)
    q=sub.add_parser("discover");q.add_argument("--component",required=True)
    sub.add_parser("scan")
    q=sub.add_parser("resolve");q.add_argument("report",type=Path);q.add_argument("--file",required=True);q.add_argument("--note-file",type=Path,required=True)
    q=sub.add_parser("review");q.add_argument("report",type=Path);q.add_argument("--note-file",type=Path,required=True)
    q=sub.add_parser("admit");q.add_argument("report",type=Path);q.add_argument("--confirm",required=True)
    a=p.parse_args();project=a.project.resolve()
    if a.command=="scan":
        import subprocess
        sources=read_json(project/"maintenance/upstreams.json");items=[]
        for config in sources["components"]+sources.get("extractedAdapters",[]):
            command=[sys.executable,str(Path(__file__).resolve()),"--project",str(project),"--state",str(a.state),"discover","--component",config["id"]]
            run=subprocess.run(command,capture_output=True,text=True,encoding="utf-8")
            if run.returncode:items.append({"component":config["id"],"status":"source-or-candidate-unavailable-needs-maintenance"})
            else:
                value=json.loads(run.stdout);items.append({"component":config["id"],"status":value["status"],"candidateCommit":value.get("candidateCommit"),"project":value.get("project")})
        print(json.dumps({"status":"configured-upstreams-scanned","items":items},ensure_ascii=False,indent=2));return
    if a.command=="discover":
        sources=read_json(project/"maintenance/upstreams.json");config=next((x for x in sources["components"]+sources.get("extractedAdapters",[]) if x["id"]==a.component),None)
        if not config:raise SafetyError("upstream-not-in-explicit-source-config")
        if config.get("mode")=="extracted-core-no-whole-file-replacement":
            old=config["adoptedCommit"];reader,new=fetch_component(a.state,config,old)
            if old==new:result={"status":"unchanged","component":a.component}
            else:
                dest=a.state/"candidates"/(a.component+"-"+new[:12]);dest.mkdir(parents=True,exist_ok=True)
                if (dest/"candidate.json").is_file():
                    print(json.dumps(read_json(dest/"candidate.json")|{"status":"existing-candidate"},ensure_ascii=False));return
                result={"status":"adapter-candidate-needs-maintenance-extraction-review","component":a.component,"source":config["repository"],"adoptedCommit":old,"candidateCommit":new,"changes":reader.changes(old,new),"merchantFile":config["merchantFile"],"merchantSha256":hashlib.sha256((project/config["merchantFile"]).read_bytes()).hexdigest(),"stableWorkspaceModified":False,"admission":"not-admitted"};atomic_json(dest/"candidate.json",result)
        else:
            prov=read_json(project/"mature"/a.component/"provenance.json");reader,new=fetch_component(a.state,config,prov["upstreamCommit"])
            result=candidate(project,a.state/"candidates",config,reader,new)
    elif a.command=="resolve":
        result=read_json(a.report);item=next((x for x in result["conflicts"] if x["file"]==a.file),None)
        if not item or item["reason"]!="three-way-conflict":raise SafetyError("candidate-needs-explicit-base-or-mapping-resolution")
        notes=a.note_file.read_text(encoding="utf-8")
        if not notes.strip():raise SafetyError("actual-conflict-resolution-note-required")
        root=Path(result["project"])/"mature"/result["component"];path=safe_join(root,a.file)
        incoming=safe_join(a.report.parent/"conflicts",a.file);incoming=incoming.with_suffix(incoming.suffix+".incoming")
        provenance=read_json(root/"provenance.json");record=provenance["files"][a.file]
        record.update(upstreamSha256=hashlib.sha256(incoming.read_bytes()).hexdigest(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),adapted=path.read_bytes()!=incoming.read_bytes())
        atomic_json(root/"provenance.json",provenance);result["conflicts"].remove(item);result.setdefault("resolutions",[]).append({"file":a.file,"note":notes});result["status"]="candidate-needs-review" if not result["conflicts"] else "conflict";result["checks"]["threeWayByteMerge"]="conflict-resolved-by-maintenance" if not result["conflicts"] else "conflict";atomic_json(a.report,result)
    elif a.command=="review":
        result=read_json(a.report)
        if result["conflicts"]:raise SafetyError("candidate-conflicts-need-actual-resolution")
        notes=a.note_file.read_text(encoding="utf-8")
        if not notes.strip():raise SafetyError("candidate-review-evidence-required")
        if any(x["kind"].startswith(("A","R","C")) and (x["newPath"].endswith((".py",".js",".json",".mjs",".txt"))) for x in result["unmappedChanges"]):raise SafetyError("new-tool-or-dependency-explicit-source-mapping-required")
        # Evidence belongs to the maintainer review, not an automatic semantic-safe label.
        result.update(admission="maintenance-reviewed",reviewNote=notes);atomic_json(a.report,result)
    else:
        result=read_json(a.report)
        if a.confirm!="MAINTENANCE_ADMIT" or result.get("admission")!="maintenance-reviewed":raise SafetyError("maintenance-admission-required")
        dest=project/"mature"/result["component"];old=read_json(dest/"provenance.json")
        if old["upstreamCommit"]!=result["adoptedCommit"]:raise SafetyError("stable-base-changed-rebuild-candidate")
        for name,record in old["files"].items():
            if hashlib.sha256(safe_join(dest,name).read_bytes()).hexdigest()!=record["sha256"]:raise SafetyError("merchant-adaptation-changed-rebuild-candidate")
        copy=Path(result["project"]);provenance=read_json(copy/"mature"/result["component"] /"provenance.json")
        source_files(copy)  # License/hash/path verification; not a business test.
        for name,record in provenance["files"].items():
            source=safe_join(copy/"mature"/result["component"],name);target=safe_join(dest,name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
        for name in set(old["files"])-set(provenance["files"]):safe_join(dest,name).unlink()
        provenance.pop("candidateOnly",None);atomic_json(dest/"provenance.json",provenance)
        registry=read_json(project/"registry.json")
        for item in registry["capabilities"]:
            if item.get("source",{}).get("repository")==provenance["repository"]:item["source"].update(commit=provenance["upstreamCommit"],version=provenance["upstreamVersion"])
        atomic_json(project/"registry.json",registry)
        result["admission"]="admitted-to-working-tree-not-published";atomic_json(a.report,result)
        sources=read_json(project/"maintenance/upstreams.json");config=next(x for x in sources["components"] if x["id"]==result["component"]);config["files"]=result["fileMappings"];config["adoptedCommit"]=provenance["upstreamCommit"];atomic_json(project/"maintenance/upstreams.json",sources)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
