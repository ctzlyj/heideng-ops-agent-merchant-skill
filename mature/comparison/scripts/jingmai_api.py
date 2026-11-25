"""Official Jingmai reads and confirmed price-only writes with persisted readback."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from jd_price_adjustment import calculate_final_price, canonical_spec, normalize_size
from merchant_runtime import RuntimeConfigurationError, merchant_path, official_executable
from store_pricing import PolicyError, PolicyStore, activity_rates, canonical, digest, evaluate, fresh, money, read_identity, timestamp, write_json

ENDPOINTS = {
    "products": ("jdo-product-status", "/rest/sp-product/v0/products"),
    "skus": ("jdo-product-status", "/rest/sp-product/v0/skus"),
    "detail": ("jdo-product-update", "/rest/sp-product/v0/products/{productId}"),
    "application": ("jdo-product-update", "/rest/sp-product/v0/product-apply/{applyId}"),
    "price_stars": ("jdo-product-price", "/rest/sp-product/v0/price-stars"),
}


class ApiError(PolicyError):
    pass


def require(condition, code):
    if not condition:
        raise ApiError(code)


def identifier(value):
    result = str(value)
    require(bool(re.fullmatch(r"[1-9][0-9]{0,19}", result)), "INVALID_PLATFORM_ID")
    return result


def ids(values):
    result = [identifier(value) for value in values]
    require(len(result) == len(set(result)), "DUPLICATE_SCOPE_IDS")
    return result


def price_body(product_id, category, changes):
    product_id = identifier(product_id)
    require(bool(changes) and len(changes) <= 50, "INVALID_PATCH_SIZE")
    require(bool(category.get("lastCategoryId")), "CATEGORY_REQUIRED")
    category = {key: int(identifier(value)) for key, value in category.items()
                if key in {"firstCategoryId", "secondCategoryId", "thirdCategoryId", "lastCategoryId"} and value}
    return {"applyId": product_id, "opType": 3, "scene": "pop",
            "productInfo": {"productId": int(product_id), "categoryDetail": category},
            "productApplyDTO": {"id": product_id},
            "patchOperationList": [{"path": f"skus[skuId=={identifier(sku)}]",
                                    "value": canonical({"componentCode": "SkuJdprice", "value": str(money(price, positive=True))})}
                                   for sku, price in changes.items()]}


def validate_body(product_id, body):
    try:
        changes = {}
        for operation in body["patchOperationList"]:
            match = re.fullmatch(r"skus\[skuId==([0-9]+)\]", operation["path"])
            require(match is not None, "PRICE_ONLY_PATCH_REQUIRED")
            value = json.loads(operation["value"])
            require(set(value) == {"componentCode", "value"} and value["componentCode"] == "SkuJdprice", "PRICE_ONLY_PATCH_REQUIRED")
            require(match[1] not in changes, "DUPLICATE_PATCH_SKU")
            changes[match[1]] = value["value"]
        expected = price_body(product_id, body["productInfo"]["categoryDetail"], changes)
        require(body == expected, "PRICE_ONLY_PATCH_REQUIRED")
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ApiError("PRICE_ONLY_PATCH_REQUIRED") from error


class Client:
    def __init__(self, profile, executable=None, interval=0.35, max_requests=2000):
        require(bool(re.fullmatch(r"[\w-]{1,64}", profile or "")) and profile != "default", "EXPLICIT_PROFILE_REQUIRED")
        self.profile = profile
        try:
            self.executable = official_executable(executable)
        except RuntimeConfigurationError as error:
            raise ApiError(str(error)) from error
        self.interval, self.max_requests, self.request_count, self.last_request = interval, max_requests, 0, 0.0

    def throttle(self):
        require(self.request_count < self.max_requests, "REQUEST_BUDGET_EXCEEDED")
        time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        self.request_count += 1

    def identity(self):
        self.throttle()
        return read_identity(self.profile, self.executable)

    def invoke(self, skill, url, params, body=None):
        if body is None:
            require((skill, url) in ENDPOINTS.values(), "ENDPOINT_NOT_ALLOWED")
        else:
            require((skill, url) == ("jdo-product-update", "/rest/sp-product/v0/product-applies/{applyId}"), "ENDPOINT_NOT_ALLOWED")
            validate_body(params.get("applyId"), body)
            require(params == {"applyId": body["applyId"], "scene": "pop"}, "PATCH_CONTEXT_MISMATCH")
        self.throttle()
        arguments = [self.executable, "invoke", "--skill-id", skill, "--url", url,
                     "--method", "PATCH" if body is not None else "GET", "--params", canonical(params),
                     "--profile", self.profile, "--request-identity", "vender", "--timeout", "30"]
        if body is not None:
            require(len(canonical(body)) < 24000, "REQUEST_BODY_TOO_LARGE")
            arguments += ["--body", canonical(body), "--yes"]
        try:
            response = subprocess.run(arguments, capture_output=True, encoding="utf-8", text=True, timeout=40,
                                      shell=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            require(response.returncode == 0, "WRITE_OUTCOME_UNKNOWN" if body is not None else "CLI_READ_FAILED")
            result = json.loads(response.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            raise ApiError("WRITE_OUTCOME_UNKNOWN" if body is not None else "CLI_READ_FAILED") from error
        if result.get("success") is not True:
            error_text = canonical(result.get("errorList", result.get("error", {})))
            code = "API_REJECTED"
            if re.search(r"401|403|unauthor|登录|授权|权限不足", error_text, re.I):
                code = "AUTH_REQUIRED"
            elif re.search(r"429|限流|频繁|throttl|rate.?limit", error_text, re.I):
                code = "RATE_LIMIT"
            raise ApiError(code)
        return result

    def get(self, name, params):
        require(name in ENDPOINTS, "READ_ENDPOINT_NOT_ALLOWED")
        return self.invoke(*ENDPOINTS[name], params)

    def patch(self, product_id, body):
        validate_body(product_id, body)
        return self.invoke("jdo-product-update", "/rest/sp-product/v0/product-applies/{applyId}",
                           {"applyId": identifier(product_id), "scene": "pop"}, body)


def pages(client, name, params, key):
    rows, seen, total = [], set(), None
    page = 1
    while True:
        response = client.get(name, {**params, "page": page, "pageSize": 50, "sortBy": "created", "sortType": "asc"})
        metadata = response.get("paginationData") or {}
        declared = metadata.get("totalItems")
        require(declared is not None and int(declared) >= 0 and int(metadata.get("currentPage", -1)) == page, "INVALID_PAGINATION")
        require(total is None or total == int(declared), "PAGINATION_TOTAL_CHANGED")
        total = int(declared)
        current = response.get("data") or []
        require(isinstance(current, list) and len(current) == min(50, total - len(rows)), "INCOMPLETE_PAGE")
        for row in current:
            value = identifier(row[key])
            require(value not in seen, "DUPLICATE_PAGE_ID")
            seen.add(value)
            rows.append(row)
        if len(rows) == total:
            return rows
        page += 1


def get_detail(client, product_id, application=False):
    name, key = ("application", "applyId") if application else ("detail", "productId")
    data = client.get(name, {key: identifier(product_id), "scene": "pop"}).get("data")
    require(isinstance(data, dict) and identifier(data.get("productInfo", {}).get("productId")) == str(product_id), "PRODUCT_ID_MISMATCH")
    snapshot(data)
    return data


def snapshot(detail):
    product = detail["productInfo"]
    product_id = identifier(product["productId"])
    rows = detail.get("skuList")
    require(isinstance(rows, list) and bool(rows), "SKU_LIST_REQUIRED")
    sku_ids = ids([row["skuId"] for row in rows])
    require(all(str(row.get("productId")) == product_id for row in rows), "SKU_PRODUCT_MISMATCH")
    prices = {sku: str(money(row["priceInfo"]["jdPrice"], positive=True)) for sku, row in zip(sku_ids, rows)}
    require(all(Decimal(str(row["priceInfo"]["jdPrice"])) == Decimal(prices[sku]) for sku, row in zip(sku_ids, rows)), "SUBCENT_BASELINE_REVIEW_REQUIRED")
    product_keys = {"productId", "productName", "productTitle", "itemNum", "categoryDetail", "brandInfo", "logisticsInfo", "productDetailDesc", "goodsAttrInfos", "to7ReturnFlag", "productStatus"}
    sku_keys = {"skuId", "productId", "outerId", "skuName", "saleAttrs", "goodsAttrInfos", "logo", "skuEnableStatus", "valid"}
    stable = {"product": {key: product.get(key) for key in sorted(product_keys)}, "material": detail.get("material"),
              "skus": [{**{key: row.get(key) for key in sorted(sku_keys)}, "onOffShelfStatus": row.get("skuStatus", {}).get("onOffShelfStatus")}
                       for row in sorted(rows, key=lambda item: int(item["skuId"]))]}
    projection = copy.deepcopy(stable)
    status = projection["product"].get("productStatus")
    if isinstance(status, dict):
        projection["product"]["productStatus"] = {"productStatus": status.get("productStatus")}
    if isinstance(projection["material"], dict):
        projection["material"].pop("ggtImages", None)
    for row in projection["skus"]:
        row.pop("onOffShelfStatus", None)
    return {"product_id": product_id, "category": product.get("categoryDetail") or {}, "prices": prices,
            "nonprice_hash": digest(stable), "application_hash": digest(projection)}


def normalize_sku(row):
    values = [(str(item.get("attrName") or ""), "" if item.get("attrValueAlias") is None else str(item["attrValueAlias"]))
              for item in row.get("saleAttrs") or []]
    design_names = {"颜色", "款式", "图案"}
    size_fields = [(name, value) for name, value in values if name not in design_names]
    size = None
    if len(size_fields) == 1 and size_fields[0][1].strip():
        size = canonical_spec(size_fields[0][1])
    elif size_fields and all(name and value.strip() for name, value in size_fields):
        dimensions = sorted((name, canonical_spec(value)) for name, value in size_fields)
        size = "variant:" + json.dumps(dimensions, ensure_ascii=False, separators=(",", ":"))
    elif not values:
        try:
            size = normalize_size(str(row.get("skuName", "")))
        except ValueError:
            pass
    design = " / ".join(value for name, value in values if name in design_names)
    if not design:
        design = " / ".join(value for name, value in values if "尺寸" in name or "规格" in name or "尺码" in name)
    if not design:
        design = str(row.get("skuName", "")).strip()
    if size is None and not size_fields and design:
        # A product whose only variant dimension is its design has no separate size spec;
        # group it by that exact variant value so exact-SKU matching stays possible.
        size = canonical_spec(design)
    active = row.get("skuEnableStatus") == 1 and row.get("valid") == 1 and row.get("skuStatus", {}).get("onOffShelfStatus") == 1
    return {"sku_id": identifier(row["skuId"]), "product_id": identifier(row["productId"]),
            "sku_name": str(row.get("skuName", "")), "design": design, "size": size,
            "jd_price": str(money(row["priceInfo"]["jdPrice"], positive=True)), "active": active,
            "observed_hand_price": None, "price_star": None, "competitive_power": None}


def collect(client, identity, product_ids=None, sku_ids=None, all_products=False):
    require(client.identity() == identity, "IDENTITY_MISMATCH")
    require(sum(bool(value) for value in (product_ids, sku_ids, all_products)) == 1, "EXPLICIT_SINGLE_SCOPE_REQUIRED")
    chosen_skus = ids(sku_ids) if sku_ids else None
    products = ids(product_ids) if product_ids else []
    first_inventory = None
    listing_params = {"scopeSet": ["productId", "productName", "productStatus", "modified"]}
    if all_products:
        first_inventory = pages(client, "products", listing_params, "productId")
        products = [identifier(row["productId"]) for row in first_inventory]
    if chosen_skus:
        found = []
        for offset in range(0, len(chosen_skus), 50):
            found += pages(client, "skus", {"scopeSet": ["skuId", "productId", "skuName", "status"],
                                           "skuIdList": ",".join(chosen_skus[offset:offset+50])}, "skuId")
        require(set(ids([row["skuId"] for row in found])) == set(chosen_skus), "SKU_NOT_OWNED_OR_NOT_FOUND")
        products = list(dict.fromkeys(identifier(row["productId"]) for row in found))
    normalized, snapshots = [], {}
    for product_id in products:
        detail = get_detail(client, product_id)
        snapshots[product_id] = snapshot(detail)
        normalized += [normalize_sku(row) for row in detail["skuList"] if chosen_skus is None or str(row["skuId"]) in chosen_skus]
    returned_ids = ids([row["sku_id"] for row in normalized])
    require(chosen_skus is None or set(returned_ids) == set(chosen_skus), "DETAIL_SKU_SCOPE_INCOMPLETE")
    if all_products:
        after = pages(client, "products", listing_params, "productId")
        require(first_inventory == after, "INVENTORY_CHANGED_DURING_CAPTURE")
    diagnostics, warnings = {}, []
    for offset in range(0, len(returned_ids), 200):
        batch = returned_ids[offset:offset+200]
        try:
            response = client.get("price_stars", {"skuIdList": ",".join(batch), "page": 1, "pageSize": 200})
        except ApiError as error:
            if str(error) in {"AUTH_REQUIRED", "RATE_LIMIT", "REQUEST_BUDGET_EXCEEDED"}:
                raise
            warnings.append("PRICE_DIAGNOSTIC_UNAVAILABLE")
            continue
        for item in response.get("data") or []:
            sku = identifier(item["skuId"])
            require(sku in batch and sku not in diagnostics, "PRICE_DIAGNOSTIC_SCOPE_MISMATCH")
            diagnostics[sku] = item
    for row in normalized:
        item = diagnostics.get(row["sku_id"], {})
        if item.get("handPrice") is not None:
            row["observed_hand_price"] = str(money(item["handPrice"], positive=True))
        row["price_star"] = item.get("priceStar")
        row["competitive_power"] = item.get("competitivePower")
    return {"schema": "jd-api-catalog/v1", "identity": identity, "captured_at": datetime.now(timezone.utc).isoformat(),
            "skus": normalized, "products": snapshots, "whole_store": all_products,
            "activity_enrollment": "UNKNOWN", "warnings": sorted(set(warnings)), "platform_write_performed": False}


def requests_for(products, desired):
    ordered = list(desired.items())
    batches = [("mvp1", ordered[:1]), ("mvp10", ordered[1:11])]
    batches += [("batch", ordered[offset:offset+50]) for offset in range(11, len(ordered), 50)]
    owners = {sku: product_id for product_id, product in products.items() for sku in product["prices"]}
    result = []
    for phase, batch in batches:
        grouped = {}
        for sku, price in batch:
            require(sku in owners, "PATCH_SKU_NOT_IN_SNAPSHOT")
            grouped.setdefault(owners[sku], {})[sku] = price
        for product_id, changes in grouped.items():
            result.append({"request_id": str(len(result)+1), "phase": phase, "product_id": product_id,
                           "changes": changes, "body": price_body(product_id, products[product_id]["category"], changes)})
    return result


def seal(plan):
    return {**plan, "confirm_token": digest(plan)}


def prepare_plan(client, policy, source, now=None, product_ids=None, sku_ids=None):
    now = now or datetime.now(timezone.utc)
    require(source.get("mode") == "repricing", "REPRICING_PLAN_REQUIRED")
    require(source.get("shop_id") == policy["identity"]["shop_id"], "INPUT_SHOP_MISMATCH")
    fresh(source.get("captured_at"), now)
    source_gate = source.get("preflight") or {}
    require(source_gate.get("status") == "READY" and source_gate.get("purpose") in {"discovery", "price", "repricing"}, "SOURCE_PREFLIGHT_REQUIRED")
    fresh(source_gate.get("checked_at"), now)
    original_rows = source.get("own_skus", [])
    direct_table = source.get("repricing_mode") == "direct_target_table"
    if direct_table and not product_ids and not sku_ids:
        sku_ids = [str(value) for value in source.get("target_prices", {})]
    if not product_ids and not sku_ids:
        sku_ids = [row["sku_id"] for row in original_rows]
    catalog = collect(client, policy["identity"], product_ids=product_ids, sku_ids=sku_ids)
    selected = catalog["skus"]
    require(bool(selected), "EMPTY_PRICE_SCOPE")
    applications = {}
    for product_id, baseline in catalog["products"].items():
        application = snapshot(get_detail(client, product_id, application=True))
        require(application["prices"] == baseline["prices"], "APPLICATION_PRICE_BASELINE_MISMATCH")
        applications[product_id] = application
    direct, subsidy = activity_rates(source.get("activity"), policy["config"]["activity_model"], [row["sku_id"] for row in selected], now)
    original_by_id = {str(row["sku_id"]): row for row in original_rows}
    new_rows = []
    for row in selected:
        require(row["active"], "INACTIVE_SKU_REVIEW_REQUIRED")
        original = original_by_id.get(row["sku_id"], {})
        if not direct_table and original.get("size"):
            require(canonical_spec(original["size"]) == row["size"], "SOURCE_OFFICIAL_SPECIFICATION_MISMATCH")
        final_price = calculate_final_price(money(row["jd_price"]), direct, subsidy).final_price
        new_rows.append({"sku_id": row["sku_id"], "size": row["size"], "design": row["design"], "current_final_price": str(final_price)})
    normalized = copy.deepcopy(source)
    normalized["own_skus"] = new_rows
    normalized["preflight"] = {"status": "READY", "purpose": "jingmai_api", "checked_at": now.isoformat()}
    if direct_table:
        normalized.pop("competitor_skus", None)
        normalized.pop("expected_competitor_sku_ids", None)
    else:
        allowed = {"sku_id", "size", "design", "price", "url"}
        normalized["competitor_skus"] = [{key: row[key] for key in allowed} for row in source["competitor_skus"]]
    pricing = evaluate(policy, normalized, now=now)
    actual_prices = {row["sku_id"]: row["jd_price"] for row in selected}
    desired = {row["SKUID"]: row["京东价"] for row in pricing["upload_rows"] if row["京东价"] != actual_prices[row["SKUID"]]}
    return seal({"schema": "jd-api-price-plan/v1", "kind": "repricing", "identity": policy["identity"],
                 "created_at": now.isoformat(), "policy_hash": policy["confirm_token"], "source": normalized, "source_gate": source_gate,
                 "pricing": pricing, "applications": applications,
                 "current_price_basis": "LIVE_JD_PRICE_WITH_CONFIRMED_ACTIVITY_MODEL",
                 "products": catalog["products"], "desired": desired,
                 "requests": requests_for(catalog["products"], desired), "warnings": catalog["warnings"],
                 "platform_write_performed": False})


def validate_plan(plan, token):
    require(isinstance(plan, dict) and plan.get("schema") == "jd-api-price-plan/v1", "INVALID_PLAN_SCHEMA")
    require(token == plan.get("confirm_token") == digest({key: value for key, value in plan.items() if key != "confirm_token"}), "CONFIRMATION_MISMATCH")
    require(plan["requests"] == requests_for(plan["products"], plan["desired"]), "REQUEST_BODY_CHANGED")
    require(plan["kind"] in {"repricing", "rollback"}, "INVALID_PLAN_KIND")
    if plan["kind"] == "repricing":
        rows = {row["SKUID"]: row["京东价"] for row in plan["pricing"]["upload_rows"]}
        actual = {sku: price for product in plan["products"].values() for sku, price in product["prices"].items()}
        require(plan["desired"] == {sku: price for sku, price in rows.items() if actual.get(sku) != price}, "PRICING_REQUEST_MISMATCH")
    else:
        original = plan["original_plan"]
        validate_plan(original, original["confirm_token"])
        require(original["kind"] == "repricing" and original["identity"] == plan["identity"], "INVALID_ROLLBACK_ORIGIN")
        previous = {sku: value for product in original["products"].values() for sku, value in product["prices"].items()}
        require(plan["desired"] == {sku: previous[sku] for sku in original["desired"]}, "INVALID_ROLLBACK_PRICES")


def state_path(root, plan):
    return root / ("jd-pop-" + identifier(plan["identity"]["shop_id"])) / plan["confirm_token"] / "state.json"


def persist(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(canonical(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(8):
            try:
                temporary.replace(path)
                break
            except OSError as error:
                if getattr(error, "winerror", None) not in (32, 33) or attempt == 7:
                    raise
                time.sleep(min(0.05 * 2 ** attempt, 2))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def guard(detail, baseline, expected, application=False):
    observed = snapshot(detail)
    hash_key = "application_hash" if application else "nonprice_hash"
    require(observed[hash_key] == baseline[hash_key], "NONPRICE_FIELDS_CHANGED")
    require(observed["prices"] == expected, "PRICE_OR_SKU_SCOPE_CHANGED")


def guard_application(client, product_id, plan, expected_prices, require_prices=True):
    """Application views may serialize either like the detail view or like the
    pre-patch application draft; a price-only patch can rebuild the pending
    application from the online detail serialization. Both hashes are captured
    before any write, so the observed view must match one of them exactly."""
    observed = snapshot(get_detail(client, product_id, application=True))
    allowed = {plan["applications"][product_id]["application_hash"],
               plan["products"][product_id]["application_hash"]}
    require(observed["application_hash"] in allowed, "APPLICATION_NONPRICE_CHANGED")
    if require_prices:
        require(observed["prices"] == expected_prices, "PRICE_OR_SKU_SCOPE_CHANGED")
    return observed


def validate_current_policy(store, plan):
    try:
        policy = store.load(plan["identity"])
        require(policy["confirm_token"] == plan["policy_hash"], "POLICY_CHANGED")
        if plan["kind"] == "repricing":
            require(evaluate(policy, plan["source"], now=timestamp(plan["created_at"])) == plan["pricing"], "PRICING_CALCULATION_CHANGED")
        return policy
    except PolicyError as error:
        raise ApiError(str(error)) from error


def check_fresh_plan(plan, now):
    try:
        fresh(plan["created_at"], now)
        if plan["kind"] == "repricing":
            fresh(plan["source"]["captured_at"], now)
            fresh(plan["source"]["preflight"]["checked_at"], now)
            fresh(plan["source_gate"]["checked_at"], now)
            activity_rates(plan["source"]["activity"], plan["pricing"]["activity_model"],
                           [row["my_sku"] for row in plan["pricing"]["rows"]], now)
    except PolicyError as error:
        raise ApiError(str(error)) from error


def preview_plan(client, store, plan, now=None):
    validate_plan(plan, plan["confirm_token"])
    require(client.identity() == plan["identity"], "IDENTITY_MISMATCH")
    validate_current_policy(store, plan)
    check_fresh_plan(plan, now if now is not None else datetime.now(timezone.utc))
    for product_id, baseline in plan["products"].items():
        guard(get_detail(client, product_id), baseline, baseline["prices"])
        guard_application(client, product_id, plan, baseline["prices"])
    check_fresh_plan(plan, now if now is not None else datetime.now(timezone.utc))
    return {"status": "READY_FOR_CONFIRMATION", "identity": plan["identity"], "confirm_token": plan["confirm_token"],
            "request_count": len(plan["requests"]), "sku_count": len(plan["desired"]), "platform_write_performed": False}


def execute(client, store, plan, token, root, now=None, poll_count=6, poll_interval=2, read_only=False):
    validate_plan(plan, token)
    require(client.identity() == plan["identity"], "IDENTITY_MISMATCH")
    if not read_only:
        validate_current_policy(store, plan)
    try:
        root = merchant_path(root, "api-runs")
    except RuntimeConfigurationError as error:
        raise ApiError(str(error)) from error
    package = Path(__file__).resolve().parents[1]
    require(root != package and package not in root.parents, "AUDIT_MUST_BE_OUTSIDE_INSTALLATION")
    require(poll_count >= 1 and poll_interval >= 0, "INVALID_READBACK_BUDGET")
    lock = root / ("jd-pop-" + plan["identity"]["shop_id"]) / ".execute.lock"
    require(lock.resolve().is_relative_to(root), "AUDIT_PATH_ESCAPES_ROOT")
    path = state_path(root, plan)
    require(path.resolve().is_relative_to(root), "AUDIT_PATH_ESCAPES_ROOT")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise ApiError("SHOP_WRITE_LOCKED") from error
    state = None
    request_id = None
    try:
        with handle:
            handle.write(str(os.getpid()))
        archived_plan = path.with_name("plan.json")
        require(archived_plan.resolve().is_relative_to(root), "AUDIT_PATH_ESCAPES_ROOT")
        if archived_plan.exists():
            require(json.loads(archived_plan.read_text(encoding="utf-8")) == plan, "ARCHIVED_PLAN_MISMATCH")
        elif not read_only:
            persist(archived_plan, plan)
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "schema": "jd-api-price-execution/v1", "plan_hash": token, "requests": {}, "status": "CONFIRMED", "verified_skus": 0,
            "platform_write_performed": False, "platform_write_attempted": False}
        require(state.get("plan_hash") == token, "STATE_PLAN_MISMATCH")
        expected = {product_id: dict(product["prices"]) for product_id, product in plan["products"].items()}
        for request in plan["requests"]:
            request_id, product_id = request["request_id"], request["product_id"]
            baseline = plan["products"][product_id]
            old = dict(expected[product_id])
            desired = {**old, **request["changes"]}
            record = state["requests"].get(request_id)
            if record and record["status"] == "VERIFIED":
                expected[product_id] = desired
                continue
            require(client.identity() == plan["identity"], "IDENTITY_MISMATCH")
            if not read_only:
                validate_current_policy(store, plan)
            if record is None:
                if read_only:
                    state["status"] = "READY_TO_CONTINUE" if state["requests"] else "NOT_SUBMITTED"
                    return state
                guard(get_detail(client, product_id), baseline, old)
                guard_application(client, product_id, plan, old)
                check_fresh_plan(plan, now if now is not None else datetime.now(timezone.utc))
                record = {"status": "SUBMITTING", "body_hash": digest(request["body"]), "sku_ids": list(request["changes"])}
                state["requests"][request_id] = record
                state["status"] = "SUBMITTING"
                state["platform_write_attempted"] = True
                persist(path, state)
                try:
                    response = client.patch(product_id, request["body"])
                except ApiError as error:
                    record["status"] = "WRITE_OUTCOME_UNKNOWN"
                    record["error_code"] = str(error)
                    state["status"] = "WRITE_OUTCOME_UNKNOWN"
                    state["platform_write_performed"] = None
                    persist(path, state)
                    return state
                state["platform_write_performed"] = True
                record["status"] = "SUBMITTED"
                record["application_id"] = str((response.get("data") or {}).get("id", ""))
                persist(path, state)
                if record["application_id"] != product_id:
                    state["status"] = "UNEXPECTED_APPLICATION_ID"
                    persist(path, state)
                    return state
            require(record["body_hash"] == digest(request["body"]), "STATE_REQUEST_MISMATCH")
            app_snapshot = guard_application(client, product_id, plan, desired, require_prices=False)
            record["application_prices_match"] = app_snapshot["prices"] == desired
            for attempt in range(poll_count):
                live = get_detail(client, product_id)
                observed = snapshot(live)
                require(observed["nonprice_hash"] == baseline["nonprice_hash"], "NONPRICE_FIELDS_CHANGED")
                if observed["prices"] == desired and record["application_prices_match"]:
                    record["status"] = "VERIFIED"
                    record["live_prices_hash"] = digest(observed["prices"])
                    expected[product_id] = desired
                    state["platform_write_performed"] = True
                    state["verified_skus"] = sum(len(item["sku_ids"]) for item in state["requests"].values() if item["status"] == "VERIFIED")
                    persist(path, state)
                    break
                require(set(observed["prices"]) == set(old) and all(value in {old[sku], desired[sku]} for sku, value in observed["prices"].items()), "UNEXPECTED_PRICE_DURING_PROPAGATION")
                if attempt + 1 < poll_count:
                    time.sleep(poll_interval)
            if record["status"] != "VERIFIED":
                state["status"] = "PENDING_ONLINE" if record["application_prices_match"] else "WRITE_OUTCOME_UNKNOWN"
                persist(path, state)
                return state
        for product_id, prices in expected.items():
            guard(get_detail(client, product_id), plan["products"][product_id], prices)
        state["status"] = "VERIFIED"
        state["verified_skus"] = len(plan["desired"])
        persist(path, state)
        return state
    except PolicyError as error:
        if state is not None:
            state["status"] = "STOPPED"
            state["error_code"] = str(error)
            state["stopped_request"] = request_id
            persist(path, state)
        raise
    finally:
        lock.unlink()


def prepare_rollback(client, store, original, root, now=None):
    now = now or datetime.now(timezone.utc)
    validate_plan(original, original["confirm_token"])
    require(original["kind"] == "repricing", "ROLLBACK_OF_ROLLBACK_FORBIDDEN")
    path = state_path(Path(root), original)
    require(path.is_file(), "VERIFIED_EXECUTION_REQUIRED")
    state = json.loads(path.read_text(encoding="utf-8"))
    require(state.get("status") == "VERIFIED" and state.get("plan_hash") == original["confirm_token"], "VERIFIED_EXECUTION_REQUIRED")
    require(client.identity() == original["identity"], "IDENTITY_MISMATCH")
    policy = validate_current_policy(store, original)
    products, desired = {}, {}
    applications = {}
    for product_id, baseline in original["products"].items():
        expected = {**baseline["prices"], **{sku: price for sku, price in original["desired"].items() if sku in baseline["prices"]}}
        detail = get_detail(client, product_id)
        guard(detail, baseline, expected)
        products[product_id] = snapshot(detail)
        application = snapshot(get_detail(client, product_id, application=True))
        require(application["prices"] == expected, "APPLICATION_PRICE_BASELINE_MISMATCH")
        applications[product_id] = application
        desired.update({sku: price for sku, price in baseline["prices"].items() if sku in original["desired"]})
    return seal({"schema": "jd-api-price-plan/v1", "kind": "rollback", "identity": original["identity"],
                 "created_at": now.isoformat(), "policy_hash": policy["confirm_token"], "original_plan": original,
                 "products": products, "applications": applications, "desired": desired, "requests": requests_for(products, desired),
                 "platform_write_performed": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["collect", "prepare", "execute", "status", "rollback-plan"])
    parser.add_argument("--profile", required=True)
    parser.add_argument("--shop-id", required=True)
    parser.add_argument("--product-ids", help="Explicit comma-separated merchant product IDs")
    parser.add_argument("--sku-ids", help="Explicit comma-separated merchant SKU IDs")
    parser.add_argument("--all-products", action="store_true", help="Only for an explicitly authorized whole-store scope")
    parser.add_argument("--policy-dir", type=Path)
    parser.add_argument("--runs-dir", type=Path, help="Defaults to HEIDENG_MERCHANT_HOME/comparison/api-runs")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm-token")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-requests", type=int, default=2000)
    arguments = parser.parse_args()
    try:
        arguments.runs_dir = merchant_path(arguments.runs_dir, "api-runs")
        require(arguments.max_requests > 0, "INVALID_REQUEST_BUDGET")
        client = Client(arguments.profile, max_requests=arguments.max_requests)
        identity = client.identity()
        require(identity["shop_id"] == arguments.shop_id, "EXPECTED_SHOP_ID_MISMATCH")
        store = PolicyStore(arguments.policy_dir)
        product_ids = arguments.product_ids.split(",") if arguments.product_ids else None
        sku_ids = arguments.sku_ids.split(",") if arguments.sku_ids else None
        if arguments.command == "collect":
            result = collect(client, identity, product_ids, sku_ids, arguments.all_products)
        elif arguments.command == "prepare":
            require(arguments.input is not None and not arguments.all_products, "INPUT_AND_EXPLICIT_PRICE_SCOPE_REQUIRED")
            source = json.loads(arguments.input.read_text(encoding="utf-8-sig"))
            result = prepare_plan(client, store.load(identity), source, product_ids=product_ids, sku_ids=sku_ids)
        else:
            require(arguments.plan is not None, "PLAN_REQUIRED")
            plan = json.loads(arguments.plan.read_text(encoding="utf-8-sig"))
            require(plan.get("identity") == identity, "PLAN_SHOP_MISMATCH")
            if arguments.command == "rollback-plan":
                result = prepare_rollback(client, store, plan, arguments.runs_dir)
            elif arguments.command == "status":
                result = execute(client, store, plan, plan["confirm_token"], arguments.runs_dir, read_only=True)
            elif arguments.dry_run:
                result = preview_plan(client, store, plan)
            else:
                require(bool(arguments.confirm_token), "EXACT_PLAN_CONFIRMATION_REQUIRED")
                result = execute(client, store, plan, arguments.confirm_token, arguments.runs_dir)
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            write_json(arguments.output, result)
            print(json.dumps({"status": result.get("status", "READY"), "output": str(arguments.output),
                              "confirm_token": result.get("confirm_token"), "platform_write_performed": result.get("platform_write_performed", False)}, ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in (None, "READY", "VERIFIED", "READY_FOR_CONFIRMATION") else 2
    except (PolicyError, ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error) if isinstance(error, PolicyError) else type(error).__name__,
                          "next": "Inspect persisted execution state; never retry a price write merely because output or local saving failed."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
