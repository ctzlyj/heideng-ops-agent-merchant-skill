"""Shared helpers for the 京麦 main-image batch refresh pipeline.

Every step takes a single run directory. <RUN>/job.json is the only place
that names the shop, its jdo-cli profile and the target product IDs, so the
same scripts work for any store without editing code.
"""

from __future__ import annotations

from heideng_merchant.refresh_selection import plan_products

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

DEFAULT_IMAGE_BASE = "https://img10.360buyimg.com/image/"
DEFAULT_MAX_POSITION = 9
SCOPES = ("main", "detail")
SRC_ATTR = re.compile(r'(?P<attr>\b(?:data-)?src)\s*=\s*(?P<quote>["\x27])(?P<url>[^"\x27]+)(?P=quote)')


# Merchant package root only; no personal Skill search.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# ---------------------------------------------------------------- dependencies
def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_root(env_name: str, default: Path) -> Path:
    value = os.environ.get(env_name)
    return Path(value).expanduser() if value else default


def _use_vendor() -> bool:
    return bool(os.environ.get("SKILL_FORCE_VENDOR"))


def jdo_scripts_dir() -> Path:
    from heideng_merchant.mature_runtime import source_path
    entry, _ = source_path('listing')
    return entry.parent


def mover_scripts_dir() -> Path:
    """Backwards-compatible alias used by the tests and older scripts."""
    return jdo_scripts_dir()


def joyer_src_dir() -> Path:
    raise RuntimeError('company-model-sdk-not-distributed-use-mature-sufy-client')


def load_jdo():
    sys.path.insert(0, str(mover_scripts_dir()))
    import jdo_listing_mvp  # noqa: E402  (needs sys.path first)

    return jdo_listing_mvp


# --------------------------------------------------------- runtime bootstrap
def user_env(name: str) -> str:
    return ''  # No merchant credential lookup in the employee user registry.


def resolve_api_key() -> str:
    return os.environ.get('HEIDENG_MERCHANT_LTS4AI_API_KEY','').strip()


def ensure_jdo_cli() -> Path:
    from heideng_merchant.official import OfficialClient
    home=os.environ.get('HEIDENG_MERCHANT_HOME')
    if not home:raise RuntimeError('merchant-home-required')
    client=OfficialClient(Path(home))
    executable=client.executable()  # Verified independent official install only.
    os.environ['JDO_CLI_PATH']=str(executable)
    return executable


def configure_jdo_runtime(cli) -> Path:
    # Reuse the already selected mature mover's public official runtime/bridge.
    return cli.ensure_jdo_runtime()


def _python312(path) -> bool:
    if not Path(path).is_file():
        return False
    try:
        process = subprocess.run(
            [str(path), "-c", "import sys; print('%s.%s' % sys.version_info[:2])"],
            capture_output=True, timeout=30,
        )
        return process.returncode == 0 and process.stdout.strip() == b"3.12"
    except (OSError, subprocess.TimeoutExpired):
        return False


def _discover_python312() -> Path | None:
    try:
        process = subprocess.run(
            ["py", "-3.12", "-c", "import sys; print(sys.executable)"],
            capture_output=True, timeout=30,
        )
        candidate = Path(process.stdout.decode("utf-8", "replace").strip())
        if process.returncode == 0 and _python312(candidate):
            return candidate
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def ensure_python312(cli) -> Path | None:
    """Resolve and validate 3.12, including portable/venv paths with spaces."""
    candidates = [os.environ.get("JDO_PYTHON312"), sys.executable,
                  Path.home() / "AppData/Local/Programs/Python/Python312/python.exe"]
    candidates.extend(getattr(cli, "PYTHON312_CANDIDATES", ()) or ())
    discovered = None
    for candidate in candidates:
        if candidate and _python312(candidate):
            discovered = Path(candidate)
            break
    if discovered is None:
        discovered = _discover_python312()
    if discovered:
        os.environ["JDO_PYTHON312"] = str(discovered)
        # The wrapper's tuple is evaluated at import time; update it as well.
        cli.PYTHON312_CANDIDATES = (discovered,)
    return discovered


# ------------------------------------------------------------------- json I/O
def load_json(path: str | Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: str | Path, value: Any) -> None:
    """Atomic write with retries.

    Antivirus, backup agents and other user processes periodically hold the
    file open on Windows; a single os.replace then raises WinError 5 and used
    to kill a whole generate run. Retry, then fall back to an in-place write.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    last_error: Exception | None = None
    for attempt in range(8):
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.15 * (attempt + 1))
    for attempt in range(5):
        try:
            with path.open("w", encoding="utf-8") as handle:
                handle.write(payload)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.3 * (attempt + 1))
    raise OSError("cannot write %s: %s" % (path, last_error))


# ------------------------------------------------------------------ url utils
def clean_url(url: Any) -> str:
    """Normalise a platform image URL to its jfs/... key form."""
    text = str(url or "")
    return text[text.index("jfs/"):] if "jfs/" in text else text


def absolute_url(url: Any, image_base: str | None = None) -> str:
    text = str(url or "")
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("//"):
        return "https:" + text
    return (image_base or DEFAULT_IMAGE_BASE) + text.lstrip("/")


def image_key(url: Any) -> str:
    return hashlib.sha1(str(url).encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ job config
def load_job(run: str | Path) -> dict[str, Any]:
    run = Path(run)
    job = load_json(run / "job.json")
    if not job:
        raise SystemExit("missing job.json in %s (see scripts/new_job.py)" % run)
    job.setdefault("imageBase", DEFAULT_IMAGE_BASE)
    job.setdefault("size", "1024x1024")
    job.setdefault("maxPosition", DEFAULT_MAX_POSITION)
    job.setdefault("concurrency", 8)
    job.setdefault("productIds", [])
    job.setdefault("scope", "main")
    job.setdefault("detailWrite", False)
    for field in ("profile", "venderId", "shopName"):
        if job.get(field) in (None, ""):
            raise SystemExit("job.json missing required field: %s" % field)
    return job


def job_scopes(job: dict[str, Any]) -> list[str]:
    """Normalise the job scope to main / detail / both."""
    raw = job.get("scope") or "main"
    if isinstance(raw, str):
        items = [item.strip().lower() for item in raw.replace("+", ",").split(",") if item.strip()]
    else:
        items = [str(item).strip().lower() for item in raw if str(item).strip()]
    if not items or "all" in items or "both" in items:
        return list(SCOPES)
    unknown = [item for item in items if item not in SCOPES]
    if unknown:
        raise SystemExit("unknown scope value(s): %s" % ", ".join(unknown))
    return [item for item in SCOPES if item in items]


def requested_pids(job: dict[str, Any], argv: Iterable[str]) -> list[int]:
    values = [str(item) for item in argv if str(item).strip()]
    if not values:
        values = [str(item) for item in job.get("productIds") or []]
    pids: list[int] = []
    for value in values:
        for part in str(value).replace("，", ",").split(","):
            part = part.strip()
            if part:
                pids.append(int(part))
    if not pids:
        raise SystemExit("no product ids: pass them on the command line or in job.json")
    return pids


# ------------------------------------------------------------ platform access
def connect(job: dict[str, Any]):
    cli = load_jdo()
    ensure_jdo_cli()
    configure_jdo_runtime(cli)
    ensure_python312(cli)
    cli.configure_jdo_profile(job["profile"])
    return cli


def verify_identity(cli, job: dict[str, Any], run: str | Path | None = None) -> dict[str, Any]:
    """Hard gate before any write: profile, venderId and shopName must all match."""
    data = cli.get(
        "jdo-seller-info", "/rest/sp-seller/v0/venderinfo", {"scopeSet": "baseInfo"}
    ).get("data") or {}
    vender_id = int(data.get("venderId") or 0)
    shop_name = str((data.get("shopBaseInfo") or {}).get("shopName") or "")
    expected_id = int(job["venderId"])
    expected_name = str(job["shopName"])
    if (vender_id != expected_id or shop_name != expected_name
            or (job.get("shopId") and str(job["shopId"]) != str((data.get("shopBaseInfo") or {}).get("shopId") or ""))):
        raise SystemExit(
            "identity mismatch: cli=%s/%s job=%s/%s profile=%s"
            % (vender_id, shop_name, expected_id, expected_name, job["profile"])
        )
    identity = {"profile": job["profile"], "venderId": vender_id, "shopName": shop_name}
    shop_id = (data.get("shopBaseInfo") or {}).get("shopId")
    if shop_id:
        identity["shopId"] = int(shop_id)
        cli.mark_jdo_store_verified(job["profile"], vender_id, shop_name, shop_id)
    else:
        cli.mark_jdo_store_verified(job["profile"], vender_id, shop_name)
    if run is not None:
        save_json(Path(run) / "identity.json", identity)
    return identity


def apply_detail(cli, pid: int, attempts: int = 5) -> dict[str, Any]:
    last_error = None
    for attempt in range(attempts):
        try:
            return cli.get(
                "jdo-product-update",
                "/rest/sp-product/v0/product-apply/{applyId}",
                {"applyId": int(pid), "scene": "pop"},
            ).get("data") or {}
        except Exception as exc:  # noqa: BLE001 - surfaced after retries
            last_error = exc
            time.sleep(5 + attempt * 5)
    raise RuntimeError("apply-detail %s failed: %s" % (pid, last_error))


def status_int(value: Any) -> int:
    """Apply body productStatus is an object; the list API returns a plain int."""
    if isinstance(value, dict):
        value = value.get("productStatus")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def main_groups(detail: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for group in (detail.get("material") or {}).get("mainImages") or []:
        result[str(group.get("uuid"))] = [
            clean_url(item.get("imgUrl"))
            for item in sorted(
                group.get("imageInfoList") or [], key=lambda x: int(x.get("orderSort") or 0)
            )
        ]
    return result


# --------------------------------------------------------------- detail page
def detail_htmls(detail: dict[str, Any]) -> dict[str, str]:
    """Detail page lives in productInfo.productDetailDesc (PC + mobile HTML).

    material.ggtImages is the SKU spec-image echo, not the detail page.
    """
    desc = (detail.get("productInfo") or {}).get("productDetailDesc") or {}
    if not isinstance(desc, dict):
        desc = {"desc": str(desc or "")}
    return {
        "desc": str(desc.get("desc") or ""),
        "mobileDesc": str(desc.get("mobileDesc") or ""),
    }


def detail_src_urls(html: str) -> list[str]:
    return [match.group("url") for match in SRC_ATTR.finditer(html or "")]


def detail_unique_urls(html: str) -> list[str]:
    seen, result = set(), []
    for url in detail_src_urls(html):
        key = clean_url(url)
        if key not in seen:
            seen.add(key)
            result.append(url)
    return result


def rewrite_detail_html(html: str, url_map: dict[str, str]) -> tuple[str, int]:
    """Swap only the src values whose cleaned URL is planned; everything else is byte-identical."""
    replaced = 0

    def substitute(match):
        nonlocal replaced
        url = match.group("url")
        new = url_map.get(clean_url(url))
        if new is None:
            return match.group(0)
        replaced += 1
        return "%s=%s%s%s" % (match.group("attr"), match.group("quote"), new, match.group("quote"))

    return SRC_ATTR.sub(substitute, html or ""), replaced


def strip_src_values(html: str) -> str:
    """HTML with every src value removed, used to prove non-image markup is untouched."""
    return SRC_ATTR.sub(lambda match: "%s=%s<url>%s" % (match.group("attr"), match.group("quote"),
                                                       match.group("quote")), html or "")


def detail_target_size(width: int, height: int, override: str | None = None) -> str:
    """Generation size that keeps the source aspect ratio for a detail image."""
    if override:
        return str(override)
    if not width or not height:
        return "1024x1024"
    ratio = width / height
    if abs(ratio - 1) <= 0.03:
        return "1024x1024"
    scale = 1536 / max(width, height)
    snap = lambda value: max(512, int(round(value * scale / 8.0)) * 8)  # noqa: E731
    return "%dx%d" % (snap(width), snap(height))


def build_detail_plan(
    snapshots: dict[int, dict[str, Any]],
    prompt_template: str,
    image_base: str | None = None,
    order: Iterable[int] | None = None,
    size_override: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Plan detail-page images: one task per unique image per product."""
    products: list[dict[str, Any]] = []
    tasks: dict[str, dict[str, Any]] = {}
    for pid in [int(item) for item in (order if order is not None else snapshots)]:
        detail = snapshots[pid]
        info = detail.get("productInfo") or {}
        title = str(info.get("productName") or "")
        htmls = detail_htmls(detail)
        planned: dict[str, dict[str, Any]] = {}
        field_urls: dict[str, list[str]] = {}
        for field, html in htmls.items():
            field_urls[field] = [clean_url(url) for url in detail_unique_urls(html)]
            for url in field_urls[field]:
                if url not in planned:
                    key = image_key(f"{pid}|detail|{url}")
                    planned[url] = {
                        "key": key,
                        # Source file key is URL-scoped so the same physical
                        # image (main carousel, detail page, another product)
                        # is downloaded once.
                        "sourceKey": image_key(url),
                        "currentUrl": url,
                        "absoluteUrl": absolute_url(url, image_base),
                        "scope": "detail",
                        "scopes": ["detail"],
                        "productId": pid,
                        "size": size_override,
                    }
                    tasks[key] = planned[url]
        products.append(
            {
                "productId": pid,
                "title": title,
                "detailImages": list(planned.values()),
                "detailHtmlUrls": field_urls,
            }
        )
    return products, tasks


# ------------------------------------------------------------------- planning
def build_plan(
    snapshots: dict[int, dict[str, Any]],
    prompt_template: str | None = None,
    max_position: int = DEFAULT_MAX_POSITION,
    image_base: str | None = None,
    order: Iterable[int] | None = None,
    scopes: Iterable[str] = ("main",),
    detail_prompt_template: str | None = None,
    detail_size: str | None = None,
    positions: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Build the refresh plan from live apply snapshots.

    Same URL inside one product is planned once and reused by every group;
    slots beyond max_position are recorded as capped and left untouched.
    """
    products: list[dict[str, Any]] = []
    tasks: dict[str, dict[str, Any]] = {}
    capped: list[dict[str, Any]] = []
    scope_list = [item for item in SCOPES if item in set(scopes)]
    if not scope_list:
        raise SystemExit("no valid scope requested")
    position_filter = sorted({int(item) for item in positions}) if positions else []
    for pid in [int(item) for item in (order if order is not None else snapshots)]:
        detail = snapshots[pid]
        material = detail.get("material") or {}
        info = detail.get("productInfo") or {}
        title = str(info.get("productName") or "")
        groups = material.get("mainImages") or []
        rect_count = sum(
            len(group.get("imageInfoList") or [])
            for group in material.get("rectangleImages") or []
        )
        positions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for group in groups:
            uuid = str(group.get("uuid") or "0000000000")
            images = sorted(
                group.get("imageInfoList") or [], key=lambda x: int(x.get("orderSort") or 0)
            )
            for position, item in enumerate(images, 1):
                url = clean_url(item.get("imgUrl"))
                if position_filter and position not in position_filter:
                    continue
                if position > max_position:
                    capped.append(
                        {"productId": pid, "group": uuid, "position": position, "url": url}
                    )
                    continue
                if url in seen:
                    continue
                seen.add(url)
                key = image_key(f"{pid}|main|{url}")
                source_key = image_key(url)
                tasks[key] = {
                    "key": key,
                    "sourceKey": source_key,
                    "currentUrl": url,
                    "absoluteUrl": absolute_url(url, image_base),
                    "scope": "main",
                    "scopes": ["main"],
                    "group": uuid,
                    "position": position,
                    "productId": pid,
                }
                positions.append(
                    {
                        "group": uuid,
                        "position": position,
                        "key": key,
                        "url": url,
                        "sourceKey": source_key,
                    }
                )
        products.append(
            {
                "productId": pid,
                "title": title,
                "groupCount": len(groups),
                "uniqueImages": len(seen),
                "rectImages": rect_count,
                "ggtCount": len(material.get("ggtImages") or []),
                "positions": positions,
            }
        )
    if "main" not in scope_list:
        for product in products:
            product["positions"] = []
        tasks = {}

    if "detail" in scope_list:
        detail_products, detail_tasks = build_detail_plan(
            snapshots,
            detail_prompt_template or prompt_template,
            image_base,
            order,
            detail_size,
        )
        by_pid = {product["productId"]: product for product in products}
        for item in detail_products:
            target = by_pid.get(item["productId"])
            if target is None:
                target = {
                    "productId": item["productId"],
                    "title": item["title"],
                    "groupCount": 0,
                    "uniqueImages": 0,
                    "rectImages": 0,
                    "ggtCount": 0,
                    "positions": [],
                }
                products.append(target)
                by_pid[item["productId"]] = target
            target["detailImages"] = item["detailImages"]
            target["detailHtmlUrls"] = item["detailHtmlUrls"]
        for key, task in detail_tasks.items():
            if key in tasks:
                if "detail" not in tasks[key].setdefault("scopes", ["main"]):
                    tasks[key]["scopes"].append("detail")
                tasks[key]["sharedWithDetail"] = True
            else:
                tasks[key] = task

    return {
        "scopes": scope_list,
        "positionFilter": position_filter,
        "products": products,
        "tasks": tasks,
        "capped": capped,
    }


def plan_tasks(plan: dict[str, Any], pids: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
    wanted = {str(item) for item in (pids or []) if str(item).strip()}
    return {
        key: value
        for key, value in (plan.get("tasks") or {}).items()
        if not wanted or str(value.get("productId")) in wanted
    }
