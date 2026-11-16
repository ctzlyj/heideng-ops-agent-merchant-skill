#!/usr/bin/env python3
"""Capture JD detail evidence through one fixed WebCLI Chrome profile.

Raw network envelopes exist only in process memory. The output contains only
the allow-listed fields returned by ``parse_ware_business_envelope`` and never
persists signed URLs, response bodies, headers, cookies, tokens, or profiles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from browser_runtime import BrowserRuntimeError, invoke_webcli, session_name
from merchant_runtime import RuntimeConfigurationError, merchant_path
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jd_detail_evidence import (
    DetailEvidenceError,
    normalize_jd_image_url,
    parse_ware_business_envelope,
)


SKU_PATTERN = re.compile(r"\d{5,20}")
DETAIL_HOST = "api.m.jd.com"
DEFAULT_WAIT_SECONDS = 5


class WebCliCaptureError(RuntimeError):
    pass


def _sku_id(value: Any) -> str:
    text = str(value).strip()
    if not SKU_PATTERN.fullmatch(text):
        raise WebCliCaptureError("SKU_INVALID")
    return text


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            suffix=".json",
            dir=path.parent,
        ) as temporary:
            json.dump(value, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


class SubprocessWebCliClient:
    def __init__(
        self,
        profile: str,
        session: str,
        wait_seconds: int = DEFAULT_WAIT_SECONDS,
        timeout_seconds: int = 150,
    ) -> None:
        self.profile = str(profile).strip()
        self.session = str(session).strip()
        self.wait_seconds = int(wait_seconds)
        self.timeout_seconds = int(timeout_seconds)
        self.response_attempts = 5
        if not self.profile or not self.session:
            raise WebCliCaptureError("WEBCLI_PROFILE_REQUIRED")
        if self.wait_seconds < 1 or self.wait_seconds > 30:
            raise WebCliCaptureError("WAIT_SECONDS_INVALID")

    def _invoke(self, arguments: list[str]) -> str:
        try:
            return invoke_webcli(arguments, timeout=self.timeout_seconds)
        except BrowserRuntimeError as error:
            raise WebCliCaptureError(str(error)) from error

    def _invoke_json(self, arguments: list[str]) -> Any:
        try:
            payload = json.loads(self._invoke(arguments))
        except json.JSONDecodeError as error:
            raise WebCliCaptureError("WEBCLI_JSON_INVALID") from error
        if isinstance(payload, dict) and payload.get("error"):
            raise WebCliCaptureError("WEBCLI_COMMAND_FAILED")
        return payload

    def _browser(self, *arguments: str) -> list[str]:
        return [
            "webcli",
            "--profile",
            self.profile,
            "browser",
            self.session,
            "--window",
            "background",
            *arguments,
        ]

    def ensure_profile_ready(self) -> None:
        doctor = self._invoke_json(["webcli", "--json", "doctor"])
        profiles = doctor.get("profiles") if isinstance(doctor, dict) else None
        matched = next(
            (
                item
                for item in profiles or []
                if isinstance(item, dict) and item.get("contextId") == self.profile
            ),
            None,
        )
        if not matched or matched.get("extensionConnected") is not True:
            raise WebCliCaptureError("BROWSER_BRIDGE_NOT_READY")

    def open_sku(self, sku_id: str) -> None:
        capture_marker = uuid.uuid4().hex
        url = f"https://item.jd.com/{_sku_id(sku_id)}.html?jdsp_skill_probe={capture_marker}"
        self._invoke_json(self._browser("open", url))

    def verify_capture_identity(self) -> None:
        self._invoke_json(self._browser("open", "https://order.jd.com/center/list.action"))
        observed = self._invoke_json(self._browser("eval", """(() => {
            const text = (document.body?.innerText || '').slice(0, 100000);
            if (/验证码|滑块验证|完成验证/.test(text)) return {errorCode:'CAPTCHA_REQUIRED'};
            if (/passport|login|safe\\.jd/.test(location.hostname)) return {errorCode:'LOGIN_REQUIRED'};
            const selectors = ['#ttbar-login .nickname', '#ttbar-login .link-user', '.user-info .user-name', '.nickname'];
            for (const selector of selectors) {
                const element = document.querySelector(selector);
                const account = element?.textContent?.trim();
                if (account && element.getClientRects().length && !/登录|注册/.test(account))
                    return {account, host:location.hostname};
            }
            return {errorCode:'ACCOUNT_IDENTITY_UNAVAILABLE'};
        })()"""))
        if observed.get("errorCode"):
            raise WebCliCaptureError(observed["errorCode"])
        if observed.get("host") != "order.jd.com" or not observed.get("account"):
            raise WebCliCaptureError("ACCOUNT_IDENTITY_UNAVAILABLE")
        self.capture_identity = hashlib.sha256((getattr(self, "provider", "webcli") + ":" + self.profile + ":" + observed["account"]).encode()).hexdigest()

    def wait_for_page(self) -> None:
        self._invoke(self._browser("eval", """(async () => {
            const deadline = Date.now() + 15000;
            while (document.readyState === 'loading' && Date.now() < deadline)
                await new Promise(resolve => setTimeout(resolve, 200));
            return {ready: document.readyState !== 'loading'};
        })()"""))

    def page_blocker(self) -> str:
        script = (
            "(() => {"
            "const url=new URL(location.href);"
            "const text=(document.body&&document.body.innerText||'').slice(0,200000);"
            "let code='';"
            "if(/captcha|verifycode|slider/i.test(url.href)||/验证码|滑块验证|完成验证/.test(text))code='CAPTCHA_REQUIRED';"
            "else if(/safe\\.jd\\.com|risk|security/i.test(url.href)||/账号存在风险|安全验证|风险校验/.test(text))code='RISK_CONTROL';"
            "else if(/passport\\.jd\\.com|login\\.jd\\.com/i.test(url.href)||/你好，请登录|请登录后/.test(text))code='LOGIN_REQUIRED';"
            "const match=url.pathname.match(/^\\/(\\d+)\\.html$/);"
            "return {code,host:url.hostname,skuId:match?match[1]:''};"
            "})()"
        )
        result = self._invoke_json(self._browser("eval", script))
        if not isinstance(result, dict):
            return "DETAIL_PAGE_INVALID"
        code = str(result.get("code", "")).strip()
        if code:
            return code
        if result.get("host") != "item.jd.com" or not SKU_PATTERN.fullmatch(
            str(result.get("skuId", ""))
        ):
            return "DETAIL_PAGE_INVALID"
        return ""

    def network_entries(self) -> list[dict[str, Any]]:
        result = self._invoke_json(self._browser("network", "--since", "30s"))
        entries = result.get("entries") if isinstance(result, dict) else None
        return [entry for entry in entries or [] if isinstance(entry, dict)]

    def network_detail(self, key: str) -> dict[str, Any]:
        result = self._invoke_json(
            self._browser("network", "--detail", str(key), "--max-body", "0")
        )
        if not isinstance(result, dict):
            raise WebCliCaptureError("DETAIL_RESPONSE_INVALID")
        return result

    def visible_product_image(self, sku_id: str) -> str:
        expected_sku = _sku_id(sku_id)
        script = (
            "(() => {"
            "const url=new URL(location.href);"
            "const match=url.pathname.match(/^\\/(\\d+)\\.html$/);"
            "const skuId=match?match[1]:'';"
            "const selectors=['#spec-img','img.zoom-img','.preview-img img','.jqzoom img'];"
            "let image=null;"
            "for(const selector of selectors){"
            "const candidate=document.querySelector(selector);"
            "if(candidate&&candidate.getClientRects().length){image=candidate;break;}"
            "}"
            "return {skuId,imageUrl:image?(image.currentSrc||image.src||''):''};"
            "})()"
        )
        result = self._invoke_json(self._browser("eval", script))
        if not isinstance(result, dict) or str(result.get("skuId", "")) != expected_sku:
            raise WebCliCaptureError("DETAIL_PAGE_INVALID")
        return normalize_jd_image_url(result.get("imageUrl"))

    def close(self) -> None:
        self.cleanup_verified = False
        try:
            self._invoke(self._browser("close"))
            self.cleanup_verified = True
        except WebCliCaptureError:
            return


def _candidate_network_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for entry in entries:
        try:
            hostname = urlsplit(str(entry.get("url", ""))).hostname
        except ValueError:
            hostname = None
        if (
            str(entry.get("method", "")).upper() == "GET"
            and entry.get("status") == 200
            and "json" in str(entry.get("ct", "")).lower()
            and hostname == DETAIL_HOST
            and str(entry.get("key", "")).strip()
        ):
            candidates.append(entry)
    return sorted(candidates, key=lambda item: int(item.get("size") or 0), reverse=True)


def _catalog_option_groups(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    body = envelope.get("body") if isinstance(envelope, dict) else None
    color_size = body.get("colorSizeVO") if isinstance(body, dict) else None
    groups = color_size.get("colorSizeList") if isinstance(color_size, dict) else None
    result = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        values = []
        for button in group.get("buttons") or []:
            if not isinstance(button, dict):
                continue
            text = re.sub(r"\s+", " ", str(button.get("text", ""))).strip()[:300]
            if text and text not in values:
                values.append(text)
        result.append({
            "name": re.sub(r"\s+", " ", str(group.get("saleName", ""))).strip()[:120],
            "values": values[:500],
        })
    return result[:20]


def capture_sku(client: Any, sku_id: str) -> dict[str, Any]:
    expected_sku = _sku_id(sku_id)
    client.open_sku(expected_sku)
    client.wait_for_page()
    attempts = min(max(int(getattr(client, "response_attempts", 1)), 1), 5)
    for attempt in range(attempts):
        blocker = str(client.page_blocker() or "").strip()
        if blocker == "LOGIN_REQUIRED" and attempt + 1 < attempts:
            time.sleep(0.5)
            continue
        if blocker:
            raise WebCliCaptureError(blocker)
        for entry in _candidate_network_entries(client.network_entries()):
            try:
                envelope = client.network_detail(entry["key"])
                record = parse_ware_business_envelope(envelope)
            except (DetailEvidenceError, KeyError, TypeError, ValueError):
                continue
            if record.get("current_sku_id") == expected_sku:
                if not record.get("image_url"):
                    record["image_url"] = client.visible_product_image(expected_sku)
                if not record.get("image_url"):
                    raise WebCliCaptureError("DETAIL_IMAGE_EVIDENCE_MISSING")
                record["catalog_option_groups"] = _catalog_option_groups(envelope)
                return record
        if attempt + 1 < attempts:
            time.sleep(0.25)
    raise WebCliCaptureError("DETAIL_RESPONSE_NOT_FOUND")


def _catalog_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        raise WebCliCaptureError("DETAIL_RECORDS_EMPTY")
    first = records[0]
    expected = list(first.get("expected_sku_ids") or [])
    expected_set = set(expected)
    if not expected or len(expected_set) != len(expected):
        raise WebCliCaptureError("SKU_CATALOG_INVALID")
    by_sku: dict[str, dict[str, Any]] = {}
    for record in records:
        sku_id = _sku_id(record.get("current_sku_id"))
        if sku_id in by_sku:
            raise WebCliCaptureError("DUPLICATE_SKU_RESPONSE")
        if record.get("spu_id") != first.get("spu_id"):
            raise WebCliCaptureError("DETAIL_SPU_MISMATCH")
        if record.get("expected_sku_ids") != expected:
            raise WebCliCaptureError("DETAIL_SKU_MATRIX_MISMATCH")
        if record.get("request_context") != first.get("request_context"):
            raise WebCliCaptureError("DETAIL_REQUEST_CONTEXT_MISMATCH")
        if record.get("price_scene") != first.get("price_scene"):
            raise WebCliCaptureError("DETAIL_PRICE_SCENE_MISMATCH")
        if record.get("catalog_option_groups") != first.get("catalog_option_groups"):
            raise WebCliCaptureError("DETAIL_OPTION_GROUP_MISMATCH")
        by_sku[sku_id] = record
    if set(by_sku) != expected_set:
        raise WebCliCaptureError("SKU_DETAIL_EVIDENCE_INCOMPLETE")
    return {
        "status": "READY",
        "spu_id": str(first.get("spu_id", "")),
        "main_sku_id": str(first.get("main_sku_id", "")),
        "expected_sku_ids": expected,
        "price_scene": str(first.get("price_scene", "")),
        "capture_context_consistent": True,
        "catalog_option_groups": first.get("catalog_option_groups") or [],
        "sku_records": [
            {
                "sku_id": sku_id,
                "design": by_sku[sku_id]["design"],
                "raw_spec": by_sku[sku_id]["raw_spec"],
                "normalized_spec": by_sku[sku_id]["normalized_spec"],
                "final_price": by_sku[sku_id]["final_price"],
                "product_url": by_sku[sku_id]["product_url"],
                "captured_at": by_sku[sku_id]["captured_at"],
                "image_url": by_sku[sku_id]["image_url"],
                "dimension_evidence": by_sku[sku_id]["dimension_evidence"],
                "price_evidence": by_sku[sku_id]["price_evidence"],
            }
            for sku_id in expected
        ],
    }


def _public_seed(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "READY",
        "sku_id": record["current_sku_id"],
        "spu_id": record["spu_id"],
        "main_sku_id": record["main_sku_id"],
        "expected_sku_ids": record["expected_sku_ids"],
        "expected_sku_count": len(record["expected_sku_ids"]),
        "title": record["title"],
        "raw_spec": record["raw_spec"],
        "normalized_spec": record["normalized_spec"],
        "design": record["design"],
        "final_price": record["final_price"],
        "product_url": record["product_url"],
        "captured_at": record["captured_at"],
        "image_url": record["image_url"],
        "price_scene": record["price_scene"],
        "variant_evidence": record["variant_evidence"],
        "price_evidence": record["price_evidence"],
        "catalog_option_groups": record.get("catalog_option_groups") or [],
    }


def capture_seed(client: Any, entry_sku_id: str) -> dict[str, Any]:
    try:
        client.ensure_profile_ready()
        return _public_seed(capture_sku(client, entry_sku_id))
    finally:
        client.close()


def _record_is_fresh(record, now):
    try:
        captured = datetime.fromisoformat(record["captured_at"].replace("Z", "+00:00"))
        age = (now - captured).total_seconds()
        return 0 <= age <= 900
    except (KeyError, ValueError, TypeError):
        return False


def _same_capture_context(record, seed):
    return all(record.get(key) == seed.get(key) for key in (
        "spu_id", "expected_sku_ids", "request_context", "price_scene", "catalog_option_groups"))


def capture_catalog(client: Any, entry_sku_id: str, checkpoint: Path | None = None) -> dict[str, Any]:
    entry_sku = _sku_id(entry_sku_id)
    try:
        client.ensure_profile_ready()
        cached = []
        identity = None
        if checkpoint is not None:
            if hasattr(client, "verify_capture_identity"):
                client.verify_capture_identity()
            identity = getattr(client, "capture_identity", None)
            if not identity:
                raise WebCliCaptureError("CHECKPOINT_IDENTITY_REQUIRED")
            identity = hashlib.sha256(str(identity).encode()).hexdigest()
            checkpoint = merchant_path(checkpoint)
            if checkpoint.exists():
                saved = json.loads(checkpoint.read_text(encoding="utf-8"))
                if saved.get("schema") != "jd-detail-checkpoint/v1" or saved.get("entry_sku") != entry_sku:
                    raise WebCliCaptureError("CHECKPOINT_SCOPE_MISMATCH")
                if saved.get("identity_hash") != identity:
                    raise WebCliCaptureError("CHECKPOINT_IDENTITY_MISMATCH")
                cached = saved.get("records", [])
        first = capture_sku(client, entry_sku)
        records = [first]
        now = datetime.now(timezone.utc)
        if not isinstance(cached, list) or any(not isinstance(record, dict) or set(record) != set(first) for record in cached):
            raise WebCliCaptureError("CHECKPOINT_ROWS_INVALID")
        cached_ids = [record["current_sku_id"] for record in cached]
        if len(set(cached_ids)) != len(cached_ids):
            raise WebCliCaptureError("CHECKPOINT_ROWS_INVALID")
        old_seed = next((record for record in cached if record["current_sku_id"] == entry_sku), None)
        if old_seed and old_seed.get("final_price") != first.get("final_price"):
            cached = []
        previous = {record["current_sku_id"]: record for record in cached
                    if _record_is_fresh(record, now) and _same_capture_context(record, first)}
        def save():
            if checkpoint is not None:
                _atomic_write_json(checkpoint, {"schema": "jd-detail-checkpoint/v1", "entry_sku": entry_sku,
                                               "identity_hash": identity, "records": records})
        save()
        for sku_id in first["expected_sku_ids"]:
            if sku_id != entry_sku:
                record = previous.get(sku_id)
                if record is None or not _record_is_fresh(record, datetime.now(timezone.utc)):
                    record = capture_sku(client, sku_id)
                if not _same_capture_context(record, first):
                    raise WebCliCaptureError("DETAIL_REQUEST_CONTEXT_MISMATCH")
                records.append(record)
                save()
        if checkpoint is not None and not all(_record_is_fresh(record, datetime.now(timezone.utc)) for record in records):
            raise WebCliCaptureError("CAPTURE_EVIDENCE_EXPIRED")
        return _catalog_from_records(records)
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture a complete JD SPU catalog through one fixed WebCLI profile."
    )
    parser.add_argument("--profile", required=True, help="Connected Browser Bridge context ID or alias.")
    parser.add_argument("--entry-sku", required=True, help="One numeric JD SKU in the target SPU.")
    parser.add_argument("--output", type=Path, required=True, help="Sanitized catalog JSON output path.")
    parser.add_argument("--session", default=None, help="Dedicated browser session; otherwise generated per task.")
    parser.add_argument("--wait-seconds", type=int, default=DEFAULT_WAIT_SECONDS)
    parser.add_argument("--seed-only", action="store_true", help="Capture one trusted SKU plus its complete option matrix.")
    parser.add_argument("--checkpoint", type=Path, help="Private resumable checkpoint; requires fresh visible account verification.")
    arguments = parser.parse_args()
    try:
        if arguments.checkpoint is not None:
            arguments.checkpoint = merchant_path(arguments.checkpoint)
    except RuntimeConfigurationError as error:
        parser.exit(2, f"ERROR: {error}\n")
    client = SubprocessWebCliClient(
        profile=arguments.profile,
        session=arguments.session or session_name("detail"),
        wait_seconds=arguments.wait_seconds,
    )
    try:
        result = capture_seed(client, arguments.entry_sku) if arguments.seed_only else capture_catalog(client, arguments.entry_sku, checkpoint=arguments.checkpoint)
        _atomic_write_json(arguments.output, result)
    except (WebCliCaptureError, DetailEvidenceError, KeyError, TypeError, ValueError) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps({
        "status": result["status"],
        "spu_id": result["spu_id"],
        "sku_count": result.get("expected_sku_count", len(result.get("sku_records", []))),
        "output": str(arguments.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
