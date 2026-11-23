"""Idle product updates; signed release selection, immutable usage pins, original installer."""
from __future__ import annotations
import json, os, platform, re, shutil, subprocess, sys, time, uuid
from pathlib import Path
from .safety import SafetyError, atomic_json, read_json, safe_join, is_linked
from .state import FileLock
from .distribution import install_archive, install_digest, verify_install, validate_archive, version_key, rollback, RECEIPT, SKILL_NAME
from .update_catalog import GitSource, verify, canonical, digest, dependency_fingerprint

INTERVAL = 24 * 3600
LEASE_SECONDS = 2 * 3600

def area(state):
    base = Path(state).absolute()
    if any(is_linked(p) for p in (base,*base.parents)): raise SafetyError("linked-update-state-parent")
    root = base / "updates"; root.mkdir(parents=True, exist_ok=True)
    if is_linked(root): raise SafetyError("linked-update-state")
    return root

def configure(state, target, trust, host="unknown"):
    if is_linked(Path(target)): raise SafetyError("update-development-link-refused")
    root = area(state); path = root / "settings.json"
    if path.exists():
        value = read_json(path)
        if value["target"] != str(Path(target).resolve()): raise SafetyError("update-target-changed")
        # Preserve the original trust pins and the merchant's update settings.
    else:
        if trust.get("schemaVersion") != 1 or not trust.get("keys"): raise SafetyError("update-trust-not-configured")
        value = {"enabled": True, "target": str(Path(target).resolve()), "trust": trust, "host": host, "intervalSeconds": INTERVAL, "failures": 0, "nextCheckAt": 0, "status": "configured"}
        atomic_json(path, value)
    installed = verify_install(Path(target))
    if installed["valid"]:
        receipt = installed["receipt"]
        identity = {"sha256": receipt["archiveSha256"]} if "archiveSha256" in receipt else {"sourceManifestSha256": install_digest(receipt)}
        previous = read_json(root / "installed-release.json", {})
        if previous.get("version") != installed["version"] or any(previous.get(key) != val for key,val in identity.items()):
            files = {n: safe_join(Path(target), n).read_bytes() for n in receipt["files"] if "requirements" in n}
            capture_previous_version(state, Path(target))
            atomic_json(root / "installed-release.json", {"version": installed["version"], **identity, "dependencyFingerprint": dependency_fingerprint(files)})
    return value

def settings(state):
    value = read_json(area(state) / "settings.json")
    if not value: raise SafetyError("automatic-updates-not-configured")
    if not isinstance(value,dict) or not all(k in value for k in ('enabled','target','trust','intervalSeconds')) or not isinstance(value['enabled'],bool) or not isinstance(value['target'],str) or not isinstance(value['trust'],dict):raise SafetyError('update-settings-invalid')
    return value

def save_settings(state, value):
    with FileLock(area(state) / "settings.lock"):
        path = area(state) / "settings.json"; old = read_json(path,{})
        if old.get("sequence", 0) >= value.get("sequence", 0) and old.get("sequence"):
            value["sequence"] = old["sequence"]; value["catalogSha256"] = old["catalogSha256"]
        for protected in ("enabled","target","trust"):
            if protected in old: value[protected] = old[protected]
        atomic_json(path, value)

def status(state):
    root = area(state); value = read_json(root / "settings.json", {})
    if not value: return {"enabled": False, "status": "not-configured"}
    value = settings(state)
    target = Path(value["target"]); installed = verify_install(target)
    return {k: value.get(k) for k in ("enabled", "status", "nextCheckAt", "failures", "error", "candidate", "lastCheckAt", "hostRefreshRequired", "notice")} | {"diskVersion": installed.get("version"), "localInstallationValid": installed["valid"], "activeUsage": active_usage(state), "loadedContent": "not-inferred-from-disk; loaded-version-is-host-usage-reported; next-task-refresh-is-host-controlled", "privateAccess": "this-computer-user-Git-helper; no-maintainer-token"}

def set_enabled(state, enabled):
    with FileLock(area(state) / "settings.lock"):
        s = settings(state); s["enabled"] = bool(enabled); atomic_json(area(state) / "settings.json", s)
    return {"enabled": bool(enabled)}

def record_failure(state, reason, now=None):
    now = time.time() if now is None else now; s = settings(state)
    s["failures"] = min(20, s.get("failures", 0) + 1)
    reason = reason if re.fullmatch(r"[a-z0-9-]{1,120}", str(reason)) else "update-failure-details-sanitized"
    s.update(status="deferred", error=reason, nextCheckAt=now + min(7 * 86400, 900 * 2 ** min(10, s["failures"] - 1)))
    if s["failures"] >= 3: s["notice"] = "persistent-update-failure-or-private-access-required"
    save_settings(state, s); return s

def compatible(release, host=None):
    c = release.get("compatibility", {}); minimum = tuple(int(x) for x in c.get("pythonMinimum", "3.11").split("."))
    if tuple(sys.version_info[:len(minimum)]) < minimum: raise SafetyError("update-python-incompatible")
    if host is not None and c.get("hosts") and host not in c["hosts"]: raise SafetyError("update-host-incompatible")
    system = "windows-x64" if os.name == "nt" and platform.machine().lower() in ("amd64", "x86_64") else "macos-arm64" if platform.system() == "Darwin" and platform.machine() == "arm64" else "unsupported"
    if c.get("platforms") and system not in c["platforms"]: raise SafetyError("update-platform-incompatible")

def source_for(state):
    s = settings(state); t = s["trust"]
    return GitSource(area(state) / "source.git", t["repository"], t["ref"])

def load_catalog(state, source):
    s = settings(state); envelope = source.read_index(); payload = verify(envelope, s["trust"])
    if not isinstance(payload.get("expiresAt"), (int, float)) or not isinstance(payload.get("releases"), list): raise SafetyError("update-index-fields-invalid")
    h = __import__("hashlib").sha256(canonical(envelope)).hexdigest()
    with FileLock(area(state) / "catalog.lock"):
        s = settings(state)
        if payload["sequence"] < s.get("sequence", 0) or (payload["sequence"] == s.get("sequence") and s.get("catalogSha256") != h): raise SafetyError("update-index-replay-or-equivocation")
        s.update(sequence=payload["sequence"], catalogSha256=h); save_settings(state, s)
        atomic_json(area(state) / "catalog.json", envelope)
    return payload

def release_path(state, release):
    identifier = release["id"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", identifier): raise SafetyError("update-release-id-invalid")
    p = area(state) / "candidates" / (identifier + ".zip"); p.parent.mkdir(exist_ok=True); return p

def release_matches(receipt, release):
    if "archiveSha256" in receipt:
        return receipt["archiveSha256"] == release.get("sha256")
    return bool(receipt.get("sourceManifestSha256") and receipt["sourceManifestSha256"] == release.get("manifestSha256")
                and receipt["version"] == release.get("version"))

def check(state, *, source=None, force=False, now=None):
    now = time.time() if now is None else now; s = settings(state)
    if not s["enabled"] and not force: return {"status": "disabled"}
    if not force and now < s.get("nextCheckAt", 0): return {"status": "not-due"}
    try:
        source = source or source_for(state); payload = load_catalog(state, source)
        current = verify_install(Path(s["target"]))
        if not current["valid"]: raise SafetyError("update-local-modifications-or-development-link")
        releases = [x for x in payload["releases"] if x.get("status") == "stable"]
        by_version = {}; by_identifier = {}
        for x in payload["releases"]:
            if x["id"] in by_identifier and by_identifier[x["id"]] != x["sha256"]: raise SafetyError("immutable-release-id-reused")
            by_identifier[x["id"]] = x["sha256"]
        for x in releases:
            version_key(x["version"])
            if x["version"] in by_version and x["sha256"] != by_version[x["version"]]: raise SafetyError("same-version-different-artifact")
            by_version[x["version"]] = x["sha256"]
            if x["version"] == current["version"] and not release_matches(current["receipt"],x): raise SafetyError("same-version-different-artifact")
        newer = [x for x in releases if version_key(x["version"]) > version_key(current["version"])]
        release = max(newer, key=lambda x: version_key(x["version"])) if newer else None
        if release:
            compatible(release, s.get("host")); path = release_path(state, release)
            if not path.exists() or digest(path) != release["sha256"]:
                raw = source.read_blob(release["gitBlob"])
                if len(raw) != release["sizeBytes"] or len(raw) > 64 * 1024 * 1024 or __import__("hashlib").sha256(raw).hexdigest() != release["sha256"]: raise SafetyError("update-download-size-or-hash-invalid")
                tmp = path.with_suffix(".partial"); tmp.write_bytes(raw); os.replace(tmp, path)
            manifest, files = validate_archive(path)
            if manifest["version"] != release["version"]: raise SafetyError("update-package-version-mismatch")
            commits = {n.split('/')[1]: json.loads(b)['upstreamCommit'] for n,b in files.items() if n.startswith('mature/') and n.endswith('/provenance.json')}
            if commits != release.get('components', {}): raise SafetyError('update-component-manifest-mismatch')
            if release.get("manifestSha256") and __import__("hashlib").sha256(files["package-manifest.json"]).hexdigest() != release["manifestSha256"]: raise SafetyError("update-manifest-mismatch")
        revoked = any(x.get("status") == "withdrawn" and release_matches(current["receipt"],x) for x in payload["releases"])
        s = settings(state); s.update(lastCheckAt=now, nextCheckAt=now + s["intervalSeconds"], failures=0, status="downloaded" if release else "withdrawn-installed" if revoked else "up-to-date", candidate=release)
        s.pop("error", None)
        if revoked: s["notice"] = "installed-release-withdrawn; signed-recovery-or-newer-stable-required"
        else: s.pop("notice", None)
        save_settings(state, s); return {"status": s["status"], "candidate": release}
    except (SafetyError, OSError, ValueError, KeyError) as e:
        record_failure(state, str(e) if isinstance(e, SafetyError) else "update-source-or-catalog-unavailable", now); return {"status": "deferred", "error": settings(state)["error"]}

def active_usage(state, now=None):
    now = time.time() if now is None else now
    return [v for p in (area(state) / "usage").glob("*.json") if (v := read_json(p, {})).get("active") and v.get("expiresAt", 0) > now]

def usage(state, action, task_id, *, components=None, receipt=None, loaded_version=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", task_id): raise SafetyError("update-task-id-invalid")
    root = area(state); directory = root / "usage"; directory.mkdir(exist_ok=True); path = directory / (task_id + ".json")
    with FileLock(root / "usage.lock"):
        old = read_json(path)
        if action == "end":
            if old: old["active"] = False; atomic_json(path, old)
            return old or {"active": False}
        if old:
            old.update(active=True, expiresAt=time.time() + LEASE_SECONDS)
            if receipt: old["recoveryReceipt"] = str(Path(receipt).resolve())
            atomic_json(path, old); return old
        if action != "begin": raise SafetyError("usage-task-not-found")
        target = Path(settings(state)["target"])
        if loaded_version:
            version_key(loaded_version)
            found = next((p for p in (root / 'versions').glob(loaded_version + '-*/' + SKILL_NAME) if verify_install(p)['valid']), None)
            if found is not None:
                value = {'taskId':task_id,'loadedVersion':loaded_version,'packageRoot':str(found),'active':True,'expiresAt':time.time()+LEASE_SECONDS,'components':components or ['all'],'recoveryReceipt':str(Path(receipt).resolve()) if receipt else None}
                atomic_json(path,value); return value
        with FileLock(Path(state) / "install.lock", shared=True):
            installed = verify_install(target)
            if not installed["valid"]: raise SafetyError("usage-installation-modified")
            version = installed["version"]
            if loaded_version and loaded_version != version:
                raise SafetyError('requested-loaded-version-snapshot-unavailable')
            snapshot = root / "versions" / (version + "-" + install_digest(installed["receipt"])[:16]) / SKILL_NAME
            write_program_snapshot(state, target, installed["receipt"], snapshot)

        reg = read_json(snapshot / "registry.json", {})
        value = {"taskId": task_id, "loadedVersion": version, "packageRoot": str(snapshot), "active": True, "expiresAt": time.time() + LEASE_SECONDS, "components": components or ["all"], "componentCommits": {p.parent.name:read_json(p)["upstreamCommit"] for p in (snapshot/"mature").glob("*/provenance.json")}, "recoveryReceipt": str(Path(receipt).resolve()) if receipt else None}
        atomic_json(path, value); return value

def apply(state, *, source=None):
    with FileLock(area(state) / "worker.lock", timeout=.1):
        s = settings(state)
        if not s["enabled"]: return {"status": "disabled"}
        # A fresh signed catalog is mandatory before switching; cached revoked releases cannot slip through.
        result = check(state, source=source, force=True)
        if result["status"] != "downloaded": return result
        release = result["candidate"]
        with FileLock(area(state) / "usage.lock"):
            if not settings(state)["enabled"]: return {"status": "disabled"}
            if active_usage(state): return {"status": "deferred-active-usage", "diskVersion": verify_install(Path(s["target"])).get("version")}
            current = verify_install(Path(s["target"]))
            if not current["valid"]: raise SafetyError("update-local-modifications-or-development-link")
            old_catalog = read_json(area(state) / "installed-release.json", {})
            if old_catalog.get("dependencyFingerprint") and old_catalog["dependencyFingerprint"] != release.get("dependencyFingerprint"):
                s = settings(state); s["status"] = "deferred-runtime-dependency-change"; s["notice"] = "runtime-update-required"; save_settings(state, s)
                return {"status": s["status"], "actionRequired": "use-original-runtime-installer-in-idle-maintenance-window"}
            try: result = install_archive(release_path(state, release), Path(s["target"]), Path(state), expected_sha=release["sha256"])
            except SafetyError as e:
                if "busy" in str(e) or "active" in str(e): return {"status": "deferred-active-task"}
                raise
        capture_previous_version(state, Path(s["target"]))
        atomic_json(area(state) / "installed-release.json", release)
        s = settings(state); s.update(status="installed", hostRefreshRequired=True, candidate=None); save_settings(state, s)
        return result | {"currentHostTaskChanged": False, "nextTaskRefreshRequired": True}

def recover(state, *, source=None, confirm=False):
    if not confirm: raise SafetyError("controlled-recovery-confirmation-required")
    s = settings(state); payload = load_catalog(state, source or source_for(state))
    current = verify_install(Path(s["target"]))
    history = read_json(Path(state) / "install-history.json", {}); previous = read_json(Path(history.get("previous") or ".") / RECEIPT, {})
    if not current["valid"]: raise SafetyError("update-local-modifications-or-development-link")
    original = current["receipt"]
    from_hashes = {original["archiveSha256"]} if "archiveSha256" in original else {
        row["sha256"] for row in payload["releases"] if release_matches(original,row)}
    to_hashes = {row["sha256"] for row in payload["releases"] if row.get("status") == "stable" and release_matches(previous,row)}
    if not any(x.get("fromSha256") in from_hashes and x.get("toSha256") in to_hashes for x in payload.get("recoveries", [])):
        raise SafetyError("signed-controlled-recovery-not-authorized")
    with FileLock(area(state) / "usage.lock"):
        if active_usage(state): raise SafetyError("controlled-recovery-active-usage")
        result = rollback(Path(s["target"]), Path(state))  # Original verified backup path, no downgrade override.
    s.update(status="recovered", hostRefreshRequired=True); save_settings(state, s); return result

def recover_switch(state):
    from .distribution import _recover, _target
    s = settings(state)
    with FileLock(Path(state) / "install.lock"):
        _recover(_target(Path(s["target"])), Path(state))
    return verify_install(Path(s["target"]))

def maybe_schedule(state):
    root = area(state); s = read_json(root / "settings.json", {})
    if not s.get("enabled"): return
    idle_download = s.get("status") == "downloaded" and not active_usage(state)
    if not idle_download and time.time() < s.get("nextCheckAt", 0): return
    try:
        with FileLock(root / "schedule.lock", timeout=.01):
            s = settings(state)
            if time.time() < s.get("scheduledUntil", 0): return
            s["scheduledUntil"] = time.time() + 600; save_settings(state, s)
        from .runtime_dependencies import runtime_python
        target = Path(s["target"])
        subprocess.Popen([str(runtime_python(state)), "-I", "-B", str(target / "scripts/update_worker.py"), "--state", str(Path(state).resolve())], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=__import__("heideng_merchant.update_catalog", fromlist=["git_environment"]).git_environment(), creationflags=(subprocess.CREATE_NO_WINDOW | 0x00000008) if os.name == "nt" else 0, start_new_session=(os.name != 'nt'))
    except (SafetyError, OSError): pass  # Product tasks remain usable if updater cannot run.


def consume_notice(state):
    root = area(state); s = read_json(root / "settings.json", {})
    if not s.get("notice"): return None
    marker = s["notice"] + ":" + str(s.get("error", ""))
    if marker == s.get("reportedNotice"): return None
    s["reportedNotice"] = marker; save_settings(state, s)
    return {"reason": s["notice"], "error": s.get("error"), "businessUsable": True, "action": "query-update-status; grant-own-private-access-or-idle-maintenance"}


def capture_previous_version(state, target):
    """Retain verified program-only recovery code, including pre-updater backups."""
    from .distribution import _owned
    history = read_json(Path(state) / 'install-history.json', {})
    if not history.get('previous'): return None
    backup = _owned(history['previous'], Path(target).absolute(), 'backup', state)
    receipt = read_json(backup / RECEIPT, {})
    if receipt.get('skill') != SKILL_NAME: raise SafetyError('previous-update-receipt-invalid')
    snapshot = area(state) / 'versions' / (receipt['version'] + '-' + install_digest(receipt)[:16]) / SKILL_NAME
    write_program_snapshot(state, backup, receipt, snapshot)

    return snapshot


def write_program_snapshot(state, source, receipt, snapshot):
    """Resume interrupted copies only when every existing byte is unchanged and declared."""
    source=Path(source);snapshot=Path(snapshot);base=area(state)/'versions'
    if not snapshot.absolute().is_relative_to(base.absolute()) or any(is_linked(p) for p in (snapshot,*snapshot.parents)):raise SafetyError('snapshot-path-or-link-invalid')
    with FileLock(area(state)/'snapshots.lock'):
        if (snapshot/RECEIPT).exists():
            check=verify_install(snapshot)
            if not check['valid'] or install_digest(check['receipt'])!=install_digest(receipt):raise SafetyError('usage-snapshot-modified')
            return snapshot
        expected=receipt['files'];existing={p.relative_to(snapshot).as_posix() for p in snapshot.rglob('*') if p.is_file()} if snapshot.exists() else set()
        if existing-set(expected):raise SafetyError('snapshot-local-extra-files')
        for name in existing:
            path=safe_join(snapshot,name)
            if is_linked(path) or digest(path)!=expected[name]:raise SafetyError('snapshot-local-file-changed')
        snapshot.mkdir(parents=True,exist_ok=True)
        for name,sha in expected.items():
            origin=safe_join(source,name);dest=safe_join(snapshot,name)
            if is_linked(origin) or is_linked(dest) or digest(origin)!=sha:raise SafetyError('snapshot-source-changed')
            dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists():shutil.copyfile(origin,dest)
        atomic_json(snapshot/RECEIPT,receipt)
        if not verify_install(snapshot)['valid']:raise SafetyError('snapshot-copy-integrity-failed')
    return snapshot
