"""Offline price collection, scope, partial rejection, and reconciliation using the normal entry."""

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from zipfile import ZipFile


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def cli():
    args = sys.argv[1:]

    def option(key):
        return args[args.index(key) + 1]

    root = Path(sys.argv[0]).resolve().parent
    if os.name != "nt":
        root = Path(os.environ["JDO_CLI_PATH"]).parent
    data_file = root / "fixture.json"
    data = json.loads(data_file.read_bytes())
    assert args[0] == "invoke" and option("--profile") == "fixture"
    url = option("--url")
    params = json.loads(option("--params"))
    kind = option("--method")
    result = {"success": True}
    if kind == "PATCH":
        assert url.endswith("/product-applies/{applyId}") and "--yes" in args
        pid = str(params["applyId"])
        body = json.loads(option("--body"))
        data["sent"].append(pid)
        if pid == "702":
            result = {
                "success": False,
                "errorList": [{"code": "10103004000", "description": "product refused"}],
            }
        else:
            for op in body["patchOperationList"]:
                sku = op["path"].split("==")[1].rstrip("]")
                assert sku == str(int(pid) * 10)
                data["prices"][pid] = json.loads(op["value"])["value"]
            result["data"] = {"id": pid}
        write(data_file, data)
    elif kind == "GET":
        if url.endswith("/venderinfo"):
            result["data"] = {
                "venderId": 20001,
                "shopBaseInfo": {"shopId": 10001, "shopName": "Fixture shop", "type": 0},
            }
        elif url.endswith("/skus"):
            ids = set(params["skuIdList"].split(","))
            rows = [
                {"skuId": int(k) * 10, "productId": int(k)} for k in data["prices"] if str(int(k) * 10) in ids
            ]
            result.update(data=rows, paginationData={"totalItems": len(rows), "currentPage": 1})
        elif url.endswith("/price-stars"):
            result.update(
                data=[{"skuId": 7010, "handPrice": "18.55"}],
                paginationData={"totalItems": 1, "currentPage": 1},
            )
        elif url.endswith("/{productId}") or url.endswith("/{applyId}"):
            pid = str(params.get("productId") or params["applyId"])
            result["data"] = {
                "productInfo": {
                    "productId": int(pid),
                    "productName": "Fixture",
                    "categoryDetail": {"lastCategoryId": 123},
                    "productStatus": 103,
                },
                "material": {},
                "skuList": [
                    {
                        "skuId": int(pid) * 10,
                        "productId": int(pid),
                        "skuName": "Fixture A",
                        "outerId": "test",
                        "skuEnableStatus": 1,
                        "valid": 1,
                        "skuStatus": {"onOffShelfStatus": 1},
                        "priceInfo": {"jdPrice": data["prices"][pid]},
                        "saleAttrs": [
                            {"attrName": "颜色", "attrValueAlias": "A"},
                            {"attrName": "尺寸", "attrValueAlias": "60x120cm"},
                        ],
                    }
                ],
            }
        else:
            raise AssertionError(url)
    else:
        raise AssertionError(kind)
    print(json.dumps(result))


def install_fixture(state):
    tools = state / "tools"
    tools.mkdir()
    src = Path(__file__).read_bytes()
    if os.name == "nt":
        import platform
        from pip._vendor.distlib import scripts

        arch = "64-arm" if platform.machine().lower() == "arm64" else ("64" if sys.maxsize > 2**32 else "32")
        launcher = Path(scripts.__file__).with_name("t" + arch + ".exe").read_bytes()
        archive = BytesIO()
        with ZipFile(archive, "w") as z:
            z.writestr("__main__.py", src)
        exe = tools / "fixture.exe"
        exe.write_bytes(launcher + ('#!"' + sys.executable + '"\n').encode() + archive.getvalue())
    else:
        exe = tools / "fixture"
        exe.write_text(
            "#!/bin/sh\nexec "
            + shlex.quote(sys.executable)
            + " "
            + shlex.quote(str(Path(__file__).resolve()))
            + ' "$@"\n'
        )
        exe.chmod(0o755)
    write(
        tools / "official.json",
        {"root": "tools", "executable": exe.name, "executableSha256": sha256(exe.read_bytes()).hexdigest()},
    )
    return exe


def check(root, merchant, price_entry=None, compare_entry=None):
    root = root.resolve()
    with tempfile.TemporaryDirectory() as folder:
        s = Path(folder)
        exe = install_fixture(s)
        fixture = exe.parent / "fixture.json"
        write(fixture, {"prices": {"701": "20.00", "702": "20.00", "703": "20.00"}, "sent": []})
        env = dict(
            os.environ,
            HEIDENG_MERCHANT_HOME=str(s),
            JDO_CLI_PATH=str(exe),
            JDO_HOME=str(s / "cli-home/.jdo-cli"),
            HOME=str(s),
            USERPROFILE=str(s),
            PYTHONUTF8="1",
        )
        scripts = root / "mature/comparison/scripts" if merchant else root / "scripts"
        sys.path.insert(0, str(scripts))
        os.environ["HEIDENG_MERCHANT_HOME"] = str(s)
        from store_pricing import PolicyStore, legacy_config

        policy = PolicyStore(s / "policies")
        ident = {"shop_id": "10001", "vender_id": "20001", "shop_name": "Fixture shop", "type": "pop"}
        config = legacy_config()
        policy.commit(ident, config, policy.prepare(ident, config)["confirm_token"])
        if merchant:
            output = subprocess.run(
                [
                    sys.executable,
                    str(root / "install.py"),
                    "--skills-dir",
                    str(s / "skills"),
                    "--host",
                    "workbuddy",
                    "--state",
                    str(s),
                    "--offline",
                    "--no-auto-update",
                ],
                env=env,
                capture_output=True,
            )
            assert not output.returncode, output.stdout[-400:]
            prefix = [
                sys.executable,
                str(s / "skills/heideng-ops-agent-merchant/scripts/merchant.py"),
                "--state",
                str(s),
                "run",
                "price-update",
                "--",
            ]
        else:
            prefix = [sys.executable, str(scripts / "jingmai_api.py")]
        compare = (
            [sys.executable, str(scripts / "jd_price_adjustment.py")]
            if not merchant
            else [*prefix[:-2], "--entry", "scripts/jd_price_adjustment.py", "comparison", "--"]
        )
        prefix = price_entry or prefix
        compare = compare_entry or compare
        for index, competitor_spec in enumerate(
            ("10×20mm 双只装", "10×20mm 单只装", "10×20cm 双只装", "10×20×30mm 双只装")
        ):
            catalog = {
                "expected_competitor_sku_ids": ["9010"],
                "own_skus": [
                    {
                        "sku_id": "7010",
                        "size": "10×20mm 双只装",
                        "design": "A",
                        "current_final_price": "20.00",
                    }
                ],
                "competitor_skus": [
                    {
                        "sku_id": "9010",
                        "design": "A",
                        "size": competitor_spec,
                        "price": "12.34",
                        "url": "https://item.jd.com/9010.html",
                    }
                ],
            }
            write(s / "catalog.json", catalog)
            dest = s / f"match-{index}"
            m = subprocess.run(
                compare
                + [
                    "plan",
                    "--input",
                    str(s / "catalog.json"),
                    "--direct-rate",
                    "0",
                    "--subsidy-rate",
                    "0",
                    "--output-dir",
                    str(dest),
                ],
                capture_output=True,
                env=env,
                timeout=60,
            )
            assert (m.returncode == 0) == (index == 0), (competitor_spec, m.stderr[-500:])
            assert (dest / "upload_rows.json").exists() == (index == 0)

        def call(stage, *extra):
            args = prefix + [
                stage,
                "--profile",
                "fixture",
                "--shop-id",
                "10001",
                "--policy-dir",
                str(s / "policies"),
                "--runs-dir",
                str(s / "runs"),
                *map(str, extra),
            ]
            val = subprocess.run(
                args, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150
            )
            msg = val.stdout.strip() or val.stderr.strip()
            try:
                return json.loads(msg)
            except ValueError:
                raise AssertionError((stage, val.returncode, msg[-600:]))

        rows = call("collect", "--sku-ids", "7010,7020,7030")["skus"]
        evidence = [row["observed_hand_price"] for row in rows]
        assert evidence == ["18.55", None, None], evidence
        now = datetime.now(timezone.utc)
        stamp = now.isoformat()
        scope = [s + "0" for s in ("701", "702", "703")]
        data = {
            "shop_id": "10001",
            "mode": "repricing",
            "repricing_mode": "direct_target_table",
            "captured_at": stamp,
            "preflight": {"status": "READY", "purpose": "price", "checked_at": stamp},
            "price_context": "ordinary_single_item",
            "target_prices": dict.fromkeys(scope, "12.34"),
            "own_skus": [{"sku_id": v} for v in scope],
            "activity": {
                "model": "legacy_direct_subsidy_v1",
                "direct_rate": "0.15",
                "subsidy_rate": "0.15",
                "starts_at": (now - timedelta(days=1)).isoformat(),
                "ends_at": (now + timedelta(days=1)).isoformat(),
                "confirmed_at": stamp,
                "sku_ids": scope,
            },
        }
        source = s / "source.json"
        planfile = s / "plan.json"
        write(source, data)
        plan = call("prepare", "--input", source, "--sku-ids", ",".join(scope))
        assert "confirm_token" in plan, plan
        write(planfile, plan)
        wrong = call("execute", "--plan", planfile, "--confirm-token", "not-approved")
        assert wrong["status"] == "BLOCKED" and not json.loads(fixture.read_bytes())["sent"]
        run = call("execute", "--plan", planfile, "--confirm-token", plan["confirm_token"])
        sent = json.loads(fixture.read_bytes())["sent"]
        resumed = call("status", "--plan", planfile)
        assert json.loads(fixture.read_bytes())["sent"] == sent
        assert run["status"] == "REJECTED" and run["verified_skus"] == 2, run
        assert sent == ["701", "702", "703"], sent
        assert resumed["status"] == "REJECTED" and resumed["verified_skus"] == 2, resumed
        print(
            json.dumps(
                {
                    "product": "merchant" if merchant else "internal",
                    "observedPrices": evidence,
                    "wrongConfirmation": wrong["status"],
                    "batchPolicy": plan.get("batch_policy"),
                    "status": run["status"],
                    "requests": sent,
                    "afterReadOnlyStatus": resumed["status"],
                }
            )
        )


if __name__ == "__main__":
    if sys.argv[1:2] == ["invoke"]:
        cli()
    else:
        args = argparse.ArgumentParser()
        args.add_argument("root", type=Path, nargs="?", default=Path(__file__).resolve().parents[1])
        args.add_argument("--merchant", action="store_true")
        args.add_argument("--price-entry-json", type=json.loads)
        args.add_argument("--compare-entry-json", type=json.loads)
        p = args.parse_args()
        check(p.root, p.merchant or (p.root / "scripts/merchant.py").is_file(),
              p.price_entry_json, p.compare_entry_json)
