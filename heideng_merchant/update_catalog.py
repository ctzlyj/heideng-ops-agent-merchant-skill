"""Signed stable catalogs and a private, credential-delegating Git cache. No business calls."""
from __future__ import annotations
import hashlib, json, os, re, subprocess, time
from pathlib import Path
from .safety import SafetyError, atomic_json, is_linked

DOMAIN = b"heideng-merchant-stable-index-v1\0"
MAX_BYTES = 64 * 1024 * 1024

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

def sign(payload, key, key_id):
    return {"payload": payload, "keyId": key_id, "signature": key.sign(DOMAIN + canonical(payload)).hex()}

def verify(envelope, trust, now=None):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        payload = envelope["payload"]
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(trust["keys"][envelope["keyId"]]))
        key.verify(bytes.fromhex(envelope["signature"]), DOMAIN + canonical(payload))
        if payload["schemaVersion"] != 1 or payload["repository"] != trust["repository"] or type(payload["sequence"]) is not int or payload["sequence"] < 1: raise ValueError()
        if "expiresAt" in payload and payload["expiresAt"] <= (time.time() if now is None else now): raise ValueError()
        return payload
    except ImportError: raise SafetyError("update-signature-runtime-unavailable") from None
    except Exception: raise SafetyError("update-catalog-signature-or-source-invalid") from None

def repository_url(repository):
    if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository): raise SafetyError("update-repository-not-allowed")
    return "https://github.com/" + repository + ".git"

def git_environment():
    # Git itself uses THIS computer user's credential helper; no token export, login or maintainer key delivery.
    names = ("PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA")
    env = {k: os.environ[k] for k in names if k in os.environ}
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_CONFIG_NOSYSTEM="0", PYTHONIOENCODING="utf-8")
    return env

class GitSource:
    def __init__(self, cache, repository, ref="refs/heads/codex/merchant-foundation"):
        raw_path = Path(cache).absolute()
        if any(is_linked(p) for p in (raw_path,*raw_path.parents)): raise SafetyError("linked-update-cache")
        self.cache = raw_path.resolve(); self.repository = repository; self.url = repository_url(repository)
        if not re.fullmatch(r"refs/(heads|tags)/[A-Za-z0-9_./-]+", ref) or ".." in ref: raise SafetyError("update-ref-invalid")
        self.ref = ref
        self.cache.mkdir(parents=True, exist_ok=True)
        if self.cache.is_symlink(): raise SafetyError("linked-update-cache")
        if not (self.cache / "HEAD").exists(): self.run("init", "--bare")
    def run(self, *args, timeout=120):
        try:
            p = subprocess.run(["git", "-c", "credential.interactive=false", "-c", "http.sslVerify=true", "-C", str(self.cache), *args], env=git_environment(), capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired): raise SafetyError("update-git-or-source-unavailable") from None
        if p.returncode: raise SafetyError("update-private-source-unreachable-or-access-required")
        if len(p.stdout) > MAX_BYTES: raise SafetyError("update-source-too-large")
        return p.stdout
    def fetch(self):
        self.run("fetch", "--quiet", "--depth=1", "--no-tags", self.url, "+" + self.ref + ":refs/heideng/catalog")
    def read_index(self):
        self.fetch()
        raw = self.run("show", "refs/heideng/catalog:updates/stable-index.json")
        if len(raw) > 1024 * 1024: raise SafetyError("update-index-too-large")
        return json.loads(raw)
    def read_blob(self, oid):
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(oid)): raise SafetyError("update-blob-id-invalid")
        if int(self.run("cat-file", "-s", oid).strip()) > MAX_BYTES: raise SafetyError("update-artifact-too-large")
        if self.run("cat-file", "-t", oid).strip() != b"blob": raise SafetyError("update-artifact-not-blob")
        return self.run("cat-file", "blob", oid)


def dependency_fingerprint(files):
    names = sorted(n for n in files if "requirements" in n and n.endswith(".txt"))
    return hashlib.sha256(b"".join(n.encode() + b"\0" + files[n] + b"\0" for n in names)).hexdigest()
