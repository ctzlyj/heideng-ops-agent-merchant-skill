"""Read-only browser selection, authenticated discovery gate and resumable JD capture."""

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from browser_runtime import BrowserRuntimeError, WebCliRunner, choose_provider, session_name
from merchant_runtime import RuntimeConfigurationError, merchant_path
from webcli_jd_detail_capture import SubprocessWebCliClient, WebCliCaptureError, capture_catalog, capture_seed, _atomic_write_json, _sku_id
from webcli_jd_search_capture import SubprocessWebCliSearchClient, SearchCaptureError, capture_title_search, _validate_source


def checked_client(provider, profile, runner=None):
    if provider not in {"auto", "webcli"}:
        raise BrowserRuntimeError("BROWSER_PROVIDER_INVALID")
    runner = runner or WebCliRunner()
    doctor = runner.json(["--json", "doctor"])
    connected = [item for item in doctor.get("profiles", []) if item.get("extensionConnected")
                 and (not profile or item.get("contextId") == profile)]
    if len(connected) > 1:
        raise BrowserRuntimeError("EXPLICIT_BROWSER_PROFILE_REQUIRED")
    if not connected:
        raise BrowserRuntimeError("BROWSER_BRIDGE_NOT_READY")
    selected, profile = "webcli", connected[0]["contextId"]
    client = SubprocessWebCliClient(profile, session_name("preflight"))
    client.provider = selected
    try:
        client.ensure_profile_ready()
        client.verify_capture_identity()
        capabilities = {selected: {"connected": True, "authorized": bool(client.capture_identity), "capabilities": ["detail", "search"]}}
        if choose_provider(capabilities) != selected:
            raise BrowserRuntimeError("BROWSER_CAPABILITY_NOT_READY")
        return client, selected
    except Exception:
        client.close()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preflight", "detail", "search"])
    parser.add_argument("--provider", choices=["auto", "webcli"], default="auto")
    parser.add_argument("--profile")
    parser.add_argument("--entry-sku")
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--keyword")
    parser.add_argument("--own-shop", action="append", default=[])
    parser.add_argument("--search-role", choices=["supplement", "independent", "fallback"], default="supplement")
    parser.add_argument("--image-search-issue", default="")
    parser.add_argument("--image-search-observation", default="")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-image-tools", action="store_true")
    arguments = parser.parse_args()
    client = None
    collection_started = False
    try:
        if arguments.require_image_tools and any(importlib.util.find_spec(name) is None for name in ("PIL", "openpyxl")):
            raise BrowserRuntimeError("IMAGE_TOOLS_REQUIRED")
        if arguments.command == "detail" and not arguments.entry_sku:
            raise BrowserRuntimeError("ENTRY_SKU_REQUIRED")
        if arguments.command == "search" and (not arguments.source or not arguments.keyword or not arguments.own_shop):
            raise BrowserRuntimeError("SEARCH_SCOPE_REQUIRED")
        if arguments.command == "detail":
            arguments.entry_sku = _sku_id(arguments.entry_sku)
        if arguments.command == "search":
            source = _validate_source(json.loads(arguments.source.read_text(encoding="utf-8-sig")))
        client, provider = checked_client(arguments.provider, arguments.profile)
        gate = {"status": "READY", "purpose": "discovery", "checked_at": datetime.now(timezone.utc).isoformat()}
        if arguments.command == "preflight":
            result = {"status": "READY", "gate": gate, "provider": provider, "identity_hash": client.capture_identity,
                      "platform_write_performed": False}
            client.close()
        elif arguments.command == "detail":
            checkpoint = merchant_path(arguments.checkpoint, "capture-runs",
                         client.capture_identity, arguments.entry_sku + ".json")
            collection_started = True
            result = capture_seed(client, arguments.entry_sku) if arguments.seed_only else capture_catalog(client, arguments.entry_sku, checkpoint=checkpoint)
            result["provider"] = provider
        else:
            client = SubprocessWebCliSearchClient(client.profile, client.session)
            collection_started = True
            result = capture_title_search(client, keyword=arguments.keyword, source=source, own_shop_names=arguments.own_shop,
                                          search_role=arguments.search_role, image_search_issue_code=arguments.image_search_issue,
                                          image_search_observation=arguments.image_search_observation)
        if not getattr(client, "cleanup_verified", False):
            raise BrowserRuntimeError("BROWSER_CLEANUP_UNVERIFIED")
        if arguments.output:
            _atomic_write_json(arguments.output, result)
            print(json.dumps({"status": result.get("status", "CAPTURED"), "provider": provider, "output": str(arguments.output), "platform_write_performed": False}))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BrowserRuntimeError, WebCliCaptureError, SearchCaptureError, RuntimeConfigurationError, ValueError, OSError, KeyError, TypeError) as error:
        if client is not None and not collection_started and not getattr(client, "cleanup_verified", False):
            client.close()
        code = str(error) if isinstance(error, (BrowserRuntimeError, WebCliCaptureError, SearchCaptureError)) else type(error).__name__
        status = "ACTION_REQUIRED" if code in {"LOGIN_REQUIRED", "CAPTCHA_REQUIRED", "ACCOUNT_IDENTITY_UNAVAILABLE", "EXPLICIT_BROWSER_PROFILE_REQUIRED", "IMAGE_TOOLS_REQUIRED"} else "BLOCKED"
        print(json.dumps({"status": status, "error": code, "platform_write_performed": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
