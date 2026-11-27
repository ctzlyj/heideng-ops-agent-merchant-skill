"""Explicit upstream delta candidates. Git merges bytes; semantic admission stays reviewed."""
from __future__ import annotations
import hashlib, json, re, subprocess, tempfile
from pathlib import Path
from .safety import SafetyError, atomic_json, read_json, safe_join
from .distribution import source_files
from .update_catalog import GitSource, git_environment

class Reader:
    def __init__(self, path): self.path = Path(path)
    def run(self, *args):
        p = subprocess.run(["git", "-C", str(self.path), *args], capture_output=True, env=git_environment())
        if p.returncode: raise SafetyError("upstream-object-or-operation-unavailable")
        return p.stdout
    def blob(self, commit, path):
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit): raise SafetyError("upstream-commit-invalid")
        if path.startswith("/") or ".." in Path(path).parts or ":" in path: raise SafetyError("upstream-path-invalid")
        return self.run("show", commit + ":" + path)
    def changes(self, old, new):
        chunks = self.run("diff", "--name-status", "-z", "--find-renames", old, new).decode("utf-8").split("\0"); rows = []; i = 0
        while i < len(chunks) and chunks[i]:
            status = chunks[i]; i += 1; first = chunks[i]; i += 1
            if status.startswith(("R", "C")):
                second = chunks[i]; i += 1
            else: second = first
            rows.append({"kind": status, "oldPath": first, "newPath": second})
        return rows

def merge_bytes(merchant, base, incoming):
    if merchant == base: return incoming, False
    if incoming == base or merchant == incoming: return merchant, False
    if any(b"\0" in v for v in (merchant, base, incoming)): return merchant, True
    with tempfile.TemporaryDirectory(prefix="heideng-three-way-") as temp:
        paths = [Path(temp) / x for x in ("merchant", "base", "upstream")]
        for p,b in zip(paths,(merchant,base,incoming)): p.write_bytes(b)
        result = subprocess.run(["git", "merge-file", "-p", *map(str, paths)], capture_output=True, env=git_environment())
        return result.stdout if result.returncode == 0 else merchant, result.returncode != 0

def candidate(project, candidates, config, reader, new_commit):
    project = Path(project).resolve(); component = config["id"]
    if not re.fullmatch(r"[a-z][a-z0-9-]*", component): raise SafetyError("upstream-component-invalid")
    root = project / "mature" / component; provenance = read_json(root / "provenance.json")
    if config["repository"] != provenance["repository"]: raise SafetyError("upstream-source-config-mismatch")
    old = provenance["upstreamCommit"]
    if new_commit == old: return {"status": "unchanged", "component": component, "commit": old}
    destination = Path(candidates) / (component + "-" + old[:12] + "-" + new_commit[:12] + "-" + hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()[:8]); report_path = destination / "candidate.json"
    if report_path.exists(): return read_json(report_path) | {"status": "existing-candidate"}
    rows = reader.changes(old, new_commit); copy = destination / "project"; copy.mkdir(parents=True)
    for name, data in source_files(project).items():
        p = safe_join(copy, name); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    target_root = copy / "mature" / component; changes_by_path = {x["oldPath"]: x for x in rows}; review = set(); conflicts = []; mapping = dict(config["files"]); unmapped = []
    for row in rows:
        name = row["newPath"]; suffix = Path(name).suffix.lower()
        if suffix in (".py", ".js", ".mjs", ".cjs", ".ps1", ".sh"): review.add("executable-behavior-and-cross-component-review")
        if "requirements" in name or "package.json" in name or name.endswith(".lock"): review.add("dependency-change-review")
        if "LICENSE" in name.upper() or "COPYING" in name.upper(): review.add("distribution-license-review")
        if row["kind"].startswith(("A", "D", "R", "C")): review.add("file-graph-and-entry-review")
        if suffix == ".md": review.add("experience-and-contract-document-review")
        if row["oldPath"] not in mapping.values(): unmapped.append(row)
    for rel, upstream_path in list(mapping.items()):
        record = provenance["files"].get(rel)
        if not record:
            row = next((x for x in rows if x["newPath"] == upstream_path and not x["kind"].startswith("D")), None)
            if not row: continue
            incoming = reader.blob(new_commit, upstream_path); dest = safe_join(target_root, rel); dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(incoming)
            sha = hashlib.sha256(incoming).hexdigest()
            provenance["files"][rel] = {"upstreamSha256": sha, "sha256": sha, "adapted": False, "upstreamPath": upstream_path}
            if rel in config.get("newEntrypoints", []): provenance["entrypoints"].append(rel)
            continue
        if record.get("upstreamCommit"):
            review.add("separately-pinned-file-see-maintenance-shared-pop")
            continue
        if not record.get("upstreamSha256"): continue
        try: base = reader.blob(old, upstream_path)
        except SafetyError: conflicts.append({"file": rel, "reason": "explicit-source-mapping-unavailable"}); continue
        if hashlib.sha256(base).hexdigest() != record["upstreamSha256"]: conflicts.append({"file": rel, "reason": "old-upstream-base-hash-mismatch"}); continue
        row = changes_by_path.get(upstream_path)
        if not row: continue
        merchant = (root / rel).read_bytes()
        if row["kind"].startswith("D"):
            if merchant != base: conflicts.append({"file": rel, "reason": "upstream-delete-merchant-adaptation"}); continue
            (target_root / rel).unlink(); provenance["files"].pop(rel)
            if rel in provenance["entrypoints"]: provenance["entrypoints"].remove(rel)
            mapping.pop(rel); continue
        incoming = reader.blob(new_commit, row["newPath"]); merged, conflict = merge_bytes(merchant, base, incoming)
        if conflict:
            conflicts.append({"file": rel, "reason": "three-way-conflict"})
            artifacts = destination / "conflicts" / rel; artifacts.parent.mkdir(parents=True, exist_ok=True)
            artifacts.with_suffix(artifacts.suffix + ".base").write_bytes(base); artifacts.with_suffix(artifacts.suffix + ".incoming").write_bytes(incoming)
            continue
        dest = safe_join(target_root, rel); dest.write_bytes(merged)
        record.update(upstreamSha256=hashlib.sha256(incoming).hexdigest(), sha256=hashlib.sha256(merged).hexdigest(), adapted=merged != incoming, upstreamPath=row["newPath"])
        mapping[rel] = row["newPath"]
    mentions = []
    for row in rows:
        if row["kind"].startswith("D"): continue
        if Path(row["newPath"]).suffix.lower() not in (".py", ".js", ".mjs", ".cjs", ".md", ".json", ".sh", ".ps1"): continue
        text = reader.blob(new_commit, row["newPath"]).decode("utf-8", "replace")
        if re.search(r"llm-gw\.jd\.local|skillhub|EasyBI|黄金眼|joybuilder|OXYGEN_API_KEY", text, re.I):
            mentions.append({"file": row["newPath"], "kind": "documentation-context-only" if row["newPath"].endswith(".md") else "executable-or-config-callpath-review-not-proven-violation"})
    if mentions: review.add("employee-channel-context-review")
    try:
        header = reader.blob(new_commit, config.get("versionFile", "SKILL.md")).decode("utf-8")
        match = re.search(r"(?m)^version:\s*[\"']?([^\s\"']+)", header)
        if match: provenance["upstreamVersion"] = match.group(1)
    except SafetyError: review.add("upstream-version-metadata-review")
    provenance["upstreamCommit"] = new_commit; provenance["candidateOnly"] = True
    atomic_json(target_root / "provenance.json", provenance)
    report = {"component": component, "source": config["repository"], "channel": config["channel"], "adoptedCommit": old, "candidateCommit": new_commit, "status": "conflict" if conflicts else "candidate-needs-review", "project": str(copy), "changes": rows, "conflicts": conflicts, "unmappedChanges": unmapped, "fileMappings": mapping, "reviewRequired": sorted(review), "internalMentions": mentions, "checks": {"threeWayByteMerge": "conflict" if conflicts else "clean", "semanticSafety": "not-established-by-AI-or-string-scan", "newDependenciesAutomaticallyInstalled": False, "outerMerchantExperience": "preserved", "stableWorkspaceModified": False}, "admission": "not-admitted"}
    atomic_json(report_path, report); return report

def fetch_component(state, config, old_commit):
    store = GitSource(Path(state) / "sources" / (config["id"] + ".git"), config["repository"], config["channel"]["ref"])
    if config["channel"]["kind"] == "semver-tags":
        tags = store.run("ls-remote", "--tags", store.url).decode().splitlines(); choices = []
        for line in tags:
            fields = line.split(); match = re.fullmatch(r"refs/tags/v?(\d+)\.(\d+)\.(\d+)", fields[-1])
            if match: choices.append((tuple(map(int,match.groups())),fields[-1]))
        if not choices: raise SafetyError("configured-stable-tag-channel-unavailable")
        store.ref = max(choices)[1]
    store.fetch(); new = store.run("rev-parse", "refs/heideng/catalog^{commit}").decode().strip()
    try: store.run("cat-file", "-e", old_commit + "^{commit}")
    except SafetyError: store.run("fetch", "--quiet", "--depth=1", "--no-tags", store.url, old_commit)
    return Reader(store.cache), new
