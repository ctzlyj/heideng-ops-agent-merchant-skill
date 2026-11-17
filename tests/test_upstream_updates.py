import hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from heideng_merchant.upstream_updates import Reader, candidate

class Upstream(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Path(self.tmp.name);self.repo=self.r/"repo";self.repo.mkdir()
        self.git("init");self.git("config","core.autocrlf","false");self.git("config","user.email","offline@example.invalid");self.git("config","user.name","Offline")
        (self.repo/"scripts").mkdir();(self.repo/"scripts/a.py").write_text("one\ntwo\nthree\n")
        self.git("add",".");self.git("commit","-m","base");self.old=self.git("rev-parse","HEAD").strip()
        self.project=self.r/"merchant";root=self.project/"mature/collection/scripts";root.mkdir(parents=True)
        (root/"a.py").write_text("merchant\ntwo\nthree\n")
        for n,b in {"SKILL.md":"---\nname: heideng-ops-agent-merchant\n---\n", "VERSION":"1.0.0","registry.json":json.dumps({"capabilities":[]})}.items():(self.project/n).write_text(b)
        (self.project/"package-files.json").write_text(json.dumps({"schemaVersion":1,"files":["SKILL.md","VERSION","registry.json"]}))
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        prov={"schemaVersion":1,"license":"MIT","repository":"owner/demo","upstreamVersion":"1.0.0","upstreamCommit":self.old,"files":{"scripts/a.py":{"upstreamSha256":sha(self.repo/"scripts/a.py"),"sha256":sha(root/"a.py"),"adapted":True}},"entrypoints":["scripts/a.py"]}
        (root.parent/"provenance.json").write_text(json.dumps(prov))
        self.config={"id":"collection","repository":"owner/demo","files":{"scripts/a.py":"scripts/a.py"},"channel":{"kind":"branch","ref":"refs/heads/main"}}
    def git(self,*args):return subprocess.check_output(["git","-C",str(self.repo),*args],stderr=subprocess.DEVNULL,text=True)
    def tearDown(self):self.tmp.cleanup()
    def test_no_change_produces_no_candidate(self):
        result=candidate(self.project,self.r/"candidates",self.config,Reader(self.repo),self.old)
        self.assertEqual(result["status"],"unchanged");self.assertFalse((self.r/"candidates").exists())
    def test_three_way_merge_preserves_merchant_and_never_touches_current(self):
        (self.repo/"scripts/a.py").write_text("one\ntwo\nupstream\n");self.git("commit","-am","new");new=self.git("rev-parse","HEAD").strip()
        result=candidate(self.project,self.r/"candidates",self.config,Reader(self.repo),new)
        text=(Path(result["project"])/"mature/collection/scripts/a.py").read_text()
        self.assertIn("merchant",text);self.assertIn("upstream",text)
        self.assertNotIn("upstream",(self.project/"mature/collection/scripts/a.py").read_text())
        self.assertEqual(candidate(self.project,self.r/"candidates",self.config,Reader(self.repo),new)["status"],"existing-candidate")
    def test_conflict_does_not_overwrite_stable(self):
        (self.repo/"scripts/a.py").write_text("other\ntwo\nthree\n");self.git("commit","-am","conflict");new=self.git("rev-parse","HEAD").strip()
        result=candidate(self.project,self.r/"candidates",self.config,Reader(self.repo),new)
        self.assertEqual(result["status"],"conflict")
        self.assertEqual((self.project/"mature/collection/scripts/a.py").read_text(),"merchant\ntwo\nthree\n")
    def test_new_dependencies_are_identified_not_blindly_included(self):
        (self.repo/"requirements.txt").write_text("new-runtime\n");self.git("add",".");self.git("commit","-m","dependency");new=self.git("rev-parse","HEAD").strip()
        result=candidate(self.project,self.r/"candidates",self.config,Reader(self.repo),new)
        self.assertTrue(any(x["newPath"]=="requirements.txt" for x in result["changes"]))
        self.assertIn("dependency-change-review",result["reviewRequired"])

    def test_explicit_new_resource_mapping_enters_candidate_package(self):
        (self.repo/"references").mkdir();(self.repo/"references/new.md").write_text("new experience")
        self.git("add",".");self.git("commit","-m","resource");new=self.git("rev-parse","HEAD").strip()
        self.config["files"]["references/new.md"]="references/new.md"
        result=candidate(self.project,self.r/"candidates",self.config,Reader(self.repo),new)
        self.assertTrue((Path(result["project"])/"mature/collection/references/new.md").is_file())
    def test_rename_is_detected_and_mapping_updated(self):
        self.git("mv","scripts/a.py","scripts/b.py");self.git("commit","-m","rename");new=self.git("rev-parse","HEAD").strip()
        result=candidate(self.project,self.r/"candidates",self.config,Reader(self.repo),new)
        self.assertEqual(result["fileMappings"]["scripts/a.py"],"scripts/b.py")
        self.assertIn("file-graph-and-entry-review",result["reviewRequired"])
    def test_upstream_delete_of_adapted_file_requires_resolution(self):
        self.git("rm","scripts/a.py");self.git("commit","-m","delete");new=self.git("rev-parse","HEAD").strip()
        result=candidate(self.project,self.r/"candidates",self.config,Reader(self.repo),new)
        self.assertEqual(result["conflicts"][0]["reason"],"upstream-delete-merchant-adaptation")

    def test_new_executable_company_channel_requires_callpath_review(self):
        (self.repo/"scripts/a.py").write_text("requests.post('https://llm-gw.jd.local/chat')\n")
        self.git("commit","-am","channel");new=self.git("rev-parse","HEAD").strip()
        result=candidate(self.project,self.r/"candidates",self.config,Reader(self.repo),new)
        self.assertIn("employee-channel-context-review",result["reviewRequired"])
        self.assertIn("callpath-review",result["internalMentions"][0]["kind"])
        self.assertEqual(result["checks"]["semanticSafety"],"not-established-by-AI-or-string-scan")
    def test_internal_system_document_mention_is_not_execution_violation(self):
        (self.repo/"references").mkdir();(self.repo/"references/scope.md").write_text("EasyBI not a merchant source")
        self.config["files"]["references/scope.md"]="references/scope.md"
        self.git("add",".");self.git("commit","-m","scope");new=self.git("rev-parse","HEAD").strip()
        result=candidate(self.project,self.r/"candidates",self.config,Reader(self.repo),new)
        self.assertEqual(result["internalMentions"][0]["kind"],"documentation-context-only")
        self.assertNotIn("executable-behavior-and-cross-component-review",result["reviewRequired"])

if __name__=="__main__":unittest.main()
