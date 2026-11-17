import json, tempfile, unittest, zipfile, hashlib
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from heideng_merchant import update_catalog as catalog
from heideng_merchant import update_client as client
from heideng_merchant.safety import SafetyError
from heideng_merchant.distribution import install_archive, SKILL_NAME


def package(root,version,body="content"):
    raw={"SKILL.md":("---\nname: "+SKILL_NAME+"\n---\n"+body).encode(),"VERSION":version.encode()}
    m={"schemaVersion":1,"skill":SKILL_NAME,"version":version,"files":{n:hashlib.sha256(b).hexdigest() for n,b in raw.items()}}
    raw["package-manifest.json"]=json.dumps(m).encode();path=root/(version+".zip")
    with zipfile.ZipFile(path,"w") as z:
        for n,b in raw.items():z.writestr(n,b)
    return path

class Updates(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Path(self.tmp.name);self.state=self.r/"state";self.target=self.r/"skills"/SKILL_NAME
        self.key=Ed25519PrivateKey.generate();self.trust={"schemaVersion":1,"repository":"ctzlyj/heideng-ops-agent-merchant-skill","ref":"refs/heads/codex/merchant-foundation","keys":{"owner":self.key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()}}
    def tearDown(self):self.tmp.cleanup()
    def test_signature_tamper_is_rejected(self):
        value=catalog.sign({"schemaVersion":1,"sequence":1,"repository":self.trust["repository"],"releases":[]},self.key,"owner")
        self.assertEqual(catalog.verify(value,self.trust)["sequence"],1)
        value["payload"]["sequence"]=2
        with self.assertRaises(SafetyError):catalog.verify(value,self.trust)
    def test_defaults_enable_updates_and_disable_is_persistent(self):
        client.configure(self.state,self.target,self.trust)
        self.assertTrue(client.status(self.state)["enabled"])
        client.set_enabled(self.state,False)
        self.assertFalse(client.status(self.state)["enabled"])
    def test_usage_pins_loaded_version_and_keeps_private_data(self):
        a=package(self.r,"1.0.0");install_archive(a,self.target,self.state,expected_sha=catalog.digest(a))
        client.configure(self.state,self.target,self.trust)
        (self.state/"private.json").write_text("private")
        lease=client.usage(self.state,"begin","task-1",components=["collection"])
        self.assertEqual(lease["loadedVersion"],"1.0.0")
        self.assertTrue((Path(lease["packageRoot"])/"SKILL.md").is_file())
        self.assertFalse((Path(lease["packageRoot"])/"private.json").exists())
        self.assertTrue(client.active_usage(self.state))
        client.usage(self.state,"end","task-1")
        self.assertFalse(client.active_usage(self.state))
    def test_backoff_does_not_disable_product(self):
        client.configure(self.state,self.target,self.trust)
        client.record_failure(self.state,"source-unreachable",now=100)
        s=client.status(self.state);self.assertTrue(s["enabled"]);self.assertGreater(s["nextCheckAt"],100)
    def test_compatibility_rejects_future_python(self):
        with self.assertRaises(SafetyError):client.compatible({"compatibility":{"pythonMinimum":"99.0","platforms":[]}})

class FakeSource:
    def __init__(self,envelope,blobs):self.envelope=envelope;self.blobs=blobs;self.calls=0
    def read_index(self):self.calls+=1;return self.envelope
    def read_blob(self,oid):return self.blobs[oid]

class UpdateFailures(unittest.TestCase):
    setUp=Updates.setUp
    tearDown=Updates.tearDown
    def start(self):
        self.a=package(self.r,"1.0.0");install_archive(self.a,self.target,self.state,expected_sha=catalog.digest(self.a));client.configure(self.state,self.target,self.trust)
    def release(self,path,status="stable"):
        with zipfile.ZipFile(path) as z:m=json.loads(z.read("package-manifest.json"));mh=hashlib.sha256(z.read("package-manifest.json")).hexdigest()
        sha=catalog.digest(path)
        return {"id":"release-"+sha[:10],"version":m["version"],"status":status,"sha256":sha,"gitBlob":sha[:40],"sizeBytes":path.stat().st_size,"manifestSha256":mh,"dependencyFingerprint":catalog.dependency_fingerprint({}),"compatibility":{"pythonMinimum":"3.11","platforms":[]}}
    def feed(self,rows,paths,sequence=1,recoveries=None):
        import time
        payload={"schemaVersion":1,"sequence":sequence,"repository":self.trust["repository"],"expiresAt":time.time()+3600,"releases":rows,"recoveries":recoveries or []}
        return FakeSource(catalog.sign(payload,self.key,"owner"),{catalog.digest(p)[:40]:p.read_bytes() for p in paths})
    def test_download_and_idle_upgrade_preserve_private_state(self):
        self.start();b=package(self.r,"1.1.0");(self.state/"unknown-receipt.json").write_text("UNKNOWN")
        s=self.feed([self.release(b)],[b]);result=client.apply(self.state,source=s)
        self.assertEqual(result["version"],"1.1.0");self.assertFalse(result["currentHostTaskChanged"])
        self.assertEqual((self.state/"unknown-receipt.json").read_text(),"UNKNOWN")
    def test_active_usage_defers_and_idle_can_resume(self):
        self.start();b=package(self.r,"1.1.0");s=self.feed([self.release(b)],[b])
        lease=client.usage(self.state,"begin","host-task")
        self.assertEqual(client.apply(self.state,source=s)["status"],"deferred-active-usage")
        client.usage(self.state,"end","host-task");self.assertEqual(client.apply(self.state,source=s)["version"],"1.1.0")
        self.assertEqual((Path(lease["packageRoot"])/"VERSION").read_text(),"1.0.0")
    def test_hash_failure_does_not_replace_old_package(self):
        self.start();b=package(self.r,"1.1.0");row=self.release(b);s=self.feed([row],[b]);s.blobs[row["gitBlob"]]=b"corrupt"
        self.assertEqual(client.apply(self.state,source=s)["status"],"deferred");self.assertEqual((self.target/"VERSION").read_text(),"1.0.0")
    def test_local_change_is_not_silently_overwritten(self):
        self.start();(self.target/"SKILL.md").write_text("local edit");b=package(self.r,"1.1.0")
        self.assertEqual(client.apply(self.state,source=self.feed([self.release(b)],[b]))["status"],"deferred")
        self.assertEqual((self.target/"SKILL.md").read_text(),"local edit")
    def test_same_version_different_content_is_rejected(self):
        self.start();b=package(self.r,"1.0.0","different")
        self.assertEqual(client.check(self.state,source=self.feed([self.release(b)],[b]),force=True)["error"],"same-version-different-artifact")
    def test_lower_version_does_not_downgrade(self):
        self.start();b=package(self.r,"0.9.0")
        self.assertEqual(client.apply(self.state,source=self.feed([self.release(b)],[b]))["status"],"up-to-date")
        self.assertEqual((self.target/"VERSION").read_text(),"1.0.0")
    def test_revocation_is_rechecked_before_apply(self):
        self.start();b=package(self.r,"1.1.0");s=self.feed([self.release(b)],[b]);client.check(self.state,source=s,force=True)
        s=self.feed([self.release(b,"withdrawn")],[b],sequence=2)
        self.assertEqual(client.apply(self.state,source=s)["status"],"up-to-date");self.assertEqual((self.target/"VERSION").read_text(),"1.0.0")
    def test_signed_controlled_recovery_reuses_verified_backup(self):
        self.start();b=package(self.r,"1.1.0");client.apply(self.state,source=self.feed([self.release(b)],[b]))
        before=self.release(b,"withdrawn");after=self.release(self.a);s=self.feed([before,after],[self.a,b],sequence=2,recoveries=[{"fromSha256":before["sha256"],"toSha256":after["sha256"]}])
        with self.assertRaises(SafetyError):client.recover(self.state,source=s)
        self.assertEqual(client.recover(self.state,source=s,confirm=True)["version"],"1.0.0")
    def test_interrupted_directory_switch_recovers_original(self):
        from unittest.mock import patch
        from heideng_merchant import distribution
        self.start();b=package(self.r,"1.1.0");original=distribution._replace_directory;count=0
        def interrupted(source,target):
            nonlocal count
            count+=1
            if count==2:raise SystemExit("simulated-process-exit")
            return original(source,target)
        with patch.object(distribution,"_replace_directory",side_effect=interrupted):
            with self.assertRaises(SystemExit):install_archive(b,self.target,self.state,expected_sha=catalog.digest(b))
        self.assertFalse(self.target.exists());self.assertTrue(client.recover_switch(self.state)["valid"])
        self.assertEqual((self.target/"VERSION").read_text(),"1.0.0")
    def test_unreachable_source_is_backed_off_without_popup_or_login(self):
        self.start()
        class Failed:
            def read_index(self):raise OSError("private source unavailable")
        self.assertEqual(client.apply(self.state,source=Failed())["status"],"deferred")
        calls=self.feed([],[])
        self.assertEqual(client.check(self.state,source=calls)["status"],"not-due");self.assertEqual(calls.calls,0)
    def test_disabled_update_does_not_read_source(self):
        self.start();client.set_enabled(self.state,False);s=self.feed([],[])
        self.assertEqual(client.apply(self.state,source=s)["status"],"disabled");self.assertEqual(s.calls,0)
    def test_catalog_replay_is_not_accepted(self):
        self.start();client.check(self.state,source=self.feed([],[],sequence=2),force=True)
        self.assertIn("replay",client.check(self.state,source=self.feed([],[],sequence=1),force=True)["error"])
    def test_runtime_delta_is_not_unconditionally_installed(self):
        self.start();b=package(self.r,"1.1.0");row=self.release(b);row["dependencyFingerprint"]="new-runtime"
        self.assertEqual(client.apply(self.state,source=self.feed([row],[b]))["status"],"deferred-runtime-dependency-change")
        self.assertEqual((self.target/"VERSION").read_text(),"1.0.0")

    def test_disable_during_download_prevents_install(self):
        self.start();b=package(self.r,"1.1.0");s=self.feed([self.release(b)],[b]);original=s.read_blob
        def disabled(oid):client.set_enabled(self.state,False);return original(oid)
        s.read_blob=disabled
        self.assertEqual(client.apply(self.state,source=s)["status"],"disabled")
        self.assertEqual((self.target/"VERSION").read_text(),"1.0.0")
    def test_background_argv_has_no_key_and_never_business(self):
        import os
        from unittest.mock import patch
        self.start()
        with patch.dict(os.environ,{"GH_TOKEN":"not-for-delivery","OXYGEN_API_KEY":"not-for-business","HEIDENG_MERCHANT_LTS4AI_API_KEY":"not-for-updater"}),patch("subprocess.Popen") as popen:
            client.maybe_schedule(self.state)
            args,kwargs=popen.call_args
            self.assertIn("update_worker.py",str(args[0]))
            for name in ("GH_TOKEN","OXYGEN_API_KEY","HEIDENG_MERCHANT_LTS4AI_API_KEY"):self.assertNotIn(name,kwargs["env"])
    def test_doc_source_key_is_not_a_new_trust_anchor_after_update(self):
        self.start();other=dict(self.trust);other["keys"]={"attacker":"00"*32}
        client.configure(self.state,self.target,other)
        self.assertEqual(client.settings(self.state)["trust"],self.trust)
    def test_failure_diagnostics_do_not_store_credential_like_text(self):
        self.start();client.record_failure(self.state,"Bearer private-value",now=100)
        self.assertEqual(client.settings(self.state)["error"],"update-failure-details-sanitized")

    def test_persistent_failure_notice_is_reported_once(self):
        self.start()
        for _ in range(3):client.record_failure(self.state,"update-private-source-unreachable-or-access-required",now=100)
        self.assertIsNotNone(client.consume_notice(self.state));self.assertIsNone(client.consume_notice(self.state))
    def test_expired_or_different_repository_catalog_is_rejected(self):
        self.start();s=self.feed([],[]);payload=s.envelope["payload"];payload["expiresAt"]=1;s.envelope=catalog.sign(payload,self.key,"owner")
        self.assertEqual(client.check(self.state,source=s,force=True)["status"],"deferred")
        s=self.feed([],[]);payload=s.envelope["payload"];payload["repository"]="other/repo";s.envelope=catalog.sign(payload,self.key,"owner")
        self.assertEqual(client.check(self.state,source=s,force=True)["status"],"deferred")

    def test_pre_upgrade_contract_snapshot_can_be_used_after_disk_update(self):
        self.start();b=package(self.r,"1.1.0");client.apply(self.state,source=self.feed([self.release(b)],[b]))
        old=client.usage(self.state,"begin","recover-old",loaded_version="1.0.0")
        self.assertEqual(old["loadedVersion"],"1.0.0");self.assertEqual((Path(old["packageRoot"])/"VERSION").read_text(),"1.0.0")
        self.assertEqual(client.status(self.state)["diskVersion"],"1.1.0")

    def test_stale_status_write_cannot_lower_verified_catalog_sequence(self):
        self.start();old=client.settings(self.state)
        client.load_catalog(self.state,self.feed([],[],sequence=2));old["failures"]=1;client.save_settings(self.state,old)
        self.assertEqual(client.settings(self.state)["sequence"],2)
    def test_interrupted_snapshot_without_receipt_is_completed_safely(self):
        from heideng_merchant.distribution import verify_install
        self.start();installed=verify_install(self.target)
        snapshot=client.area(self.state)/"versions"/("1.0.0-"+installed["receipt"]["archiveSha256"][:16])/SKILL_NAME
        snapshot.mkdir(parents=True);(snapshot/"VERSION").write_bytes((self.target/"VERSION").read_bytes())
        value=client.usage(self.state,"begin","continue-snapshot")
        self.assertTrue(verify_install(Path(value["packageRoot"]))["valid"])

    def test_corrupt_updater_settings_do_not_block_normal_product_status(self):
        import contextlib,io
        from unittest.mock import patch
        from heideng_merchant import cli
        self.start();(client.area(self.state)/"settings.json").write_text("{",encoding="utf-8")
        output=io.StringIO()
        with contextlib.redirect_stdout(output),patch.object(cli,"status",return_value={"architecture":"mature-skill-dispatch"}):
            result=cli.main(["--state",str(self.state),"status"])
        self.assertEqual(result,0)
        self.assertEqual(json.loads(output.getvalue())["architecture"],"mature-skill-dispatch")

if __name__=="__main__":unittest.main()
