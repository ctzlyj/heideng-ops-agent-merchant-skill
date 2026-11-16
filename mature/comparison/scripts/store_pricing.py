"""Shop-scoped pricing policies and local plans; never submits JD price changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from merchant_runtime import RuntimeConfigurationError, merchant_path, official_executable

from jd_price_adjustment import (
    _select_candidate, canonical_spec, create_price_plan, normalize_size, parse_rate,
    round_money, validate_competitor_catalog,
)

MODELS = {"none_v1", "direct_v1", "legacy_direct_subsidy_v1"}
MAX_AGE_SECONDS = 900


class PolicyError(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def fields(value: Any, required: set[str], optional: set[str] | None = None) -> None:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - (optional or set()):
        raise PolicyError("INVALID_FIELDS")


def money(value: Any, positive: bool = False) -> Decimal:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal("100000000"):
            raise PolicyError("INVALID_AMOUNT")
        amount = round_money(amount)
    except (InvalidOperation, TypeError) as error:
        raise PolicyError("INVALID_AMOUNT") from error
    if positive and amount <= 0:
        raise PolicyError("POSITIVE_AMOUNT_REQUIRED")
    return amount


def rate(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise PolicyError("INVALID_RATE")
        return parse_rate(result)
    except (InvalidOperation, ValueError) as error:
        raise PolicyError("INVALID_RATE") from error


def validate_identity(identity: dict[str, Any]) -> None:
    fields(identity, {"shop_id", "vender_id", "shop_name", "type"})
    if identity["type"] != "pop" or not isinstance(identity["shop_name"], str) or not identity["shop_name"].strip():
        raise PolicyError("POP_IDENTITY_REQUIRED")
    for key in ("shop_id", "vender_id"):
        if not isinstance(identity[key], str) or not re.fullmatch(r"[1-9][0-9]{0,19}", identity[key]):
            raise PolicyError("INVALID_SHOP_IDENTITY")


def read_identity(profile: str, cli_path: str | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"[\w-]{1,64}", profile or "") or profile == "default":
        raise PolicyError("EXPLICIT_PROFILE_REQUIRED")
    try:
        executable = official_executable(cli_path)
    except RuntimeConfigurationError as error:
        raise PolicyError(str(error)) from error
    command = [executable, "invoke", "--skill-id", "jdo-seller-info", "--url", "/rest/sp-seller/v0/venderinfo",
               "--method", "GET", "--params", '{"scopeSet":"baseInfo"}', "--profile", profile,
               "--request-identity", "vender", "--timeout", "25"]
    try:
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=35,
                                 shell=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if process.returncode:
            raise PolicyError("OFFICIAL_IDENTITY_REQUEST_FAILED")
        response = json.loads(process.stdout)
        if response.get("success") is not True:
            raise PolicyError("OFFICIAL_IDENTITY_REQUEST_FAILED")
        source = response["data"]["shopBaseInfo"]
        if source["type"] not in (0, "0"):
            raise PolicyError("POP_ONLY")
        identity = {"shop_id": str(source["shopId"]), "vender_id": str(response["data"]["venderId"]),
                    "shop_name": source["shopName"], "type": "pop"}
        validate_identity(identity)
        return identity
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise PolicyError("OFFICIAL_IDENTITY_UNAVAILABLE") from error


def validate_strategy(strategy: Any) -> None:
    if not isinstance(strategy, dict):
        raise PolicyError("INVALID_STRATEGY")
    kind = strategy.get("kind")
    required = {"kind", "direction"}
    if kind in ("fixed_gap", "fixed_target"):
        required.add("amount")
    elif kind == "percent_below":
        required.add("rate")
    elif kind not in ("match", "compare_only"):
        raise PolicyError("UNSUPPORTED_STRATEGY")
    fields(strategy, required)
    if strategy["direction"] not in ("all", "down_only"):
        raise PolicyError("INVALID_DIRECTION")
    if "amount" in strategy:
        money(strategy["amount"], positive=kind == "fixed_target")
    if "rate" in strategy:
        rate(strategy["rate"])


def validate_config(config: Any) -> None:
    fields(config, {"activity_model", "strategy", "limits"})
    if config["activity_model"] not in MODELS:
        raise PolicyError("UNSUPPORTED_ACTIVITY_MODEL")
    validate_strategy(config["strategy"])
    fields(config["limits"], set(), {"min_final_price", "max_change_amount"})
    for value in config["limits"].values():
        money(value)


def legacy_config() -> dict[str, Any]:
    return {"activity_model": "legacy_direct_subsidy_v1",
            "strategy": {"kind": "fixed_gap", "amount": "0.10", "direction": "all"}, "limits": {}}


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


class PolicyStore:
    def __init__(self, root: Path | None = None):
        try:
            self.root = merchant_path(root, "stores")
        except RuntimeConfigurationError as error:
            raise PolicyError(str(error)) from error
        package = Path(__file__).resolve().parents[1]
        if self.root == package or package in self.root.parents:
            raise PolicyError("CONFIG_MUST_BE_OUTSIDE_INSTALLATION")

    def directory(self, identity: dict[str, Any]) -> Path:
        validate_identity(identity)
        directory = self.root / ("jd-pop-" + identity["shop_id"])
        if directory.resolve().parent != self.root:
            raise PolicyError("UNSAFE_CONFIG_PATH")
        return directory

    def latest_revision(self, identity: dict[str, Any]) -> int:
        directory = self.directory(identity)
        revisions = sorted(int(path.stem) for path in directory.glob("*.json") if re.fullmatch(r"[0-9]{8}", path.stem))
        if revisions and revisions != list(range(1, revisions[-1] + 1)):
            raise PolicyError("CONFIG_HISTORY_INCOMPLETE")
        return revisions[-1] if revisions else 0

    def load(self, identity: dict[str, Any], revision: int | None = None) -> dict[str, Any]:
        current = self.latest_revision(identity) if revision is None else revision
        if not isinstance(current, int) or current < 1:
            raise PolicyError("CONFIG_NOT_FOUND")
        path = self.directory(identity) / f"{current:08d}.json"
        if not path.is_file() or path.is_symlink():
            raise PolicyError("CONFIG_NOT_FOUND")
        record = json.loads(path.read_text(encoding="utf-8"))
        fields(record, {"schema", "identity", "revision", "previous_hash", "config", "confirm_token"})
        if record["identity"] != identity:
            raise PolicyError("IDENTITY_MISMATCH")
        if record["schema"] != "jd-shop-policy/v1" or record["revision"] != current:
            raise PolicyError("INVALID_CONFIG_REVISION")
        validate_config(record["config"])
        if record["confirm_token"] != digest({key: value for key, value in record.items() if key != "confirm_token"}):
            raise PolicyError("CONFIG_INTEGRITY_FAILURE")
        return record

    def prepare(self, identity: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        validate_config(config)
        revision = self.latest_revision(identity)
        previous = self.load(identity) if revision else None
        record = {"schema": "jd-shop-policy/v1", "identity": identity, "revision": revision + 1,
                  "previous_hash": previous["confirm_token"] if previous else None, "config": config}
        return {**record, "confirm_token": digest(record)}

    def commit(self, identity: dict[str, Any], config: dict[str, Any], confirm_token: str) -> dict[str, Any]:
        directory = self.directory(identity)
        directory.mkdir(parents=True, exist_ok=True)
        lock = directory / ".write.lock"
        try:
            handle = lock.open("x", encoding="utf-8")
        except FileExistsError as error:
            raise PolicyError("CONFIG_LOCKED") from error
        temporary_path = None
        try:
            with handle:
                handle.write(str(os.getpid()))
            record = self.prepare(identity, config)
            if confirm_token != record["confirm_token"]:
                raise PolicyError("CONFIRMATION_MISMATCH")
            destination = directory / f'{record["revision"]:08d}.json'
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as stream:
                temporary_path = Path(stream.name)
                stream.write(canonical(record) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            if destination.exists():
                raise PolicyError("REVISION_EXISTS")
            temporary_path.replace(destination)
            return self.load(identity)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
            lock.unlink()


def timestamp(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise PolicyError("TIMEZONE_REQUIRED")
        return result
    except (TypeError, ValueError) as error:
        raise PolicyError("INVALID_TIMESTAMP") from error


def fresh(value: Any, now: datetime) -> None:
    age = (now - timestamp(value)).total_seconds()
    if age < 0 or age > MAX_AGE_SECONDS:
        raise PolicyError("STALE_OR_FUTURE_EVIDENCE")


def activity_rates(activity: Any, model: str, own_ids: list[str], now: datetime) -> tuple[Decimal, Decimal]:
    fields(activity, {"model", "direct_rate", "subsidy_rate", "starts_at", "ends_at", "confirmed_at", "sku_ids"})
    if activity["model"] != model:
        raise PolicyError("ACTIVITY_MODEL_MISMATCH")
    if not timestamp(activity["starts_at"]) <= now < timestamp(activity["ends_at"]):
        raise PolicyError("ACTIVITY_NOT_ACTIVE")
    fresh(activity["confirmed_at"], now)
    if not isinstance(activity["sku_ids"], list) or len(set(activity["sku_ids"])) != len(activity["sku_ids"]) or set(own_ids) != set(activity["sku_ids"]):
        raise PolicyError("ACTIVITY_SKU_SCOPE_MISMATCH")
    direct, subsidy = rate(activity["direct_rate"]), rate(activity["subsidy_rate"])
    if (model == "none_v1" and (direct or subsidy)) or (model == "direct_v1" and subsidy):
        raise PolicyError("ACTIVITY_RATE_MODEL_MISMATCH")
    return direct, subsidy


def target_price(strategy: dict[str, Any], competitor: Decimal, current: Decimal) -> Decimal | None:
    kind = strategy["kind"]
    if kind == "compare_only":
        return None
    if kind == "fixed_gap":
        target = competitor - money(strategy["amount"])
    elif kind == "fixed_target":
        target = money(strategy["amount"], positive=True)
    elif kind == "percent_below":
        target = round_money(competitor * (1 - rate(strategy["rate"])))
    else:
        target = competitor
    target = money(target, positive=True)
    return min(target, current) if strategy["direction"] == "down_only" else target


def evaluate(policy: dict[str, Any], source: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    validate_config(policy["config"])
    direct_table = source.get("repricing_mode") == "direct_target_table"
    required = {"shop_id", "mode", "captured_at", "preflight", "price_context", "own_skus"}
    optional = {"activity", "strategy_override", "overrides", "repricing_mode"}
    if direct_table:
        required.add("target_prices")
    else:
        required |= {"expected_competitor_sku_ids", "competitor_skus"}
    fields(source, required, optional)
    if source["shop_id"] != policy["identity"]["shop_id"]:
        raise PolicyError("INPUT_SHOP_MISMATCH")
    if source["mode"] not in ("comparison", "repricing"):
        raise PolicyError("INVALID_MODE")
    fresh(source["captured_at"], now)
    gate = source["preflight"]
    fields(gate, {"status", "purpose", "checked_at"})
    if gate["status"] != "READY" or gate["purpose"] not in ("discovery", "price", "repricing", "jingmai_api"):
        raise PolicyError("PREFLIGHT_NOT_READY")
    if source["mode"] == "repricing" and gate["purpose"] not in ("price", "repricing", "jingmai_api"):
        raise PolicyError("REPRICING_PREFLIGHT_REQUIRED")
    fresh(gate["checked_at"], now)
    if source["price_context"] != "ordinary_single_item":
        raise PolicyError("UNSUPPORTED_PRICE_CONTEXT")
    if direct_table:
        strategy = {"kind": "direct_target_table", "direction": "all"}
    else:
        strategy = source.get("strategy_override", policy["config"]["strategy"])
        validate_strategy(strategy)
        if source["mode"] == "repricing" and strategy["kind"] == "compare_only":
            raise PolicyError("COMPARISON_ONLY")
    own_rows = source["own_skus"]
    own_ids = [str(row.get("sku_id", "")) for row in own_rows]
    if not own_ids or any(not re.fullmatch(r"[0-9]+", value) for value in own_ids) or len(set(own_ids)) != len(own_ids):
        raise PolicyError("INVALID_OWN_SKUS")
    direct = subsidy = Decimal("0")
    if source["mode"] == "repricing":
        direct, subsidy = activity_rates(source.get("activity"), policy["config"]["activity_model"], own_ids, now)
    rows, upload_rows = [], []
    limits = policy["config"]["limits"]
    if direct_table:
        targets = source["target_prices"]
        if not isinstance(targets, dict) or not targets or set(targets) != set(own_ids):
            raise PolicyError("TARGET_PRICE_SCOPE_MISMATCH")
        for own in own_rows:
            sku = str(own["sku_id"])
            current = money(own["current_final_price"], positive=True)
            target = money(targets[sku], positive=True)
            if ("min_final_price" in limits and target < money(limits["min_final_price"])) or (
                "max_change_amount" in limits and abs(target - current) > money(limits["max_change_amount"])
            ):
                raise PolicyError("LIMIT_EXCEEDED")
            row = {"my_sku": sku, "current_final_price": str(current), "target_final_price": str(target),
                   "price_source": "merchant_target_price_table", "action": "KEEP" if target == current else "CHANGE"}
            if source["mode"] == "repricing" and row["action"] == "CHANGE":
                calculation = create_price_plan(target, direct, subsidy, target_gap=Decimal("0"))
                row.update(recommended_jd_price=str(calculation.jd_price), calculated_final_price=str(calculation.final_price),
                           direct_rate=str(direct), subsidy_rate=str(subsidy),
                           direct_reduction_amount=str(calculation.direct_reduction),
                           government_subsidy_amount=str(calculation.government_subsidy))
                upload_rows.append({"SKUID": row["my_sku"], "京东价": row["recommended_jd_price"]})
            rows.append(row)
    else:
        competitors = source["competitor_skus"]
        validate_competitor_catalog(source["expected_competitor_sku_ids"], competitors)
        groups: dict[str, list[dict[str, Any]]] = {}
        for competitor in competitors:
            money(competitor["price"], positive=True)
            if not re.fullmatch(r"https://item\.jd\.com/[0-9]+\.html", str(competitor["url"])):
                raise PolicyError("CLEAN_JD_ITEM_URL_REQUIRED")
            if str(competitor["url"]).split("/")[-1] != str(competitor["sku_id"]) + ".html":
                raise PolicyError("SKU_URL_MISMATCH")
            groups.setdefault(canonical_spec(str(competitor["size"])), []).append(competitor)
        overrides = source.get("overrides", {})
        if not isinstance(overrides, dict) or set(overrides) - set(own_ids):
            raise PolicyError("INVALID_OVERRIDES")
        for own in own_rows:
            own_size = canonical_spec(str(own["size"]))
            if own_size not in groups:
                raise PolicyError("EXACT_SIZE_MATCH_REQUIRED")
            selected, method, similarity = _select_candidate(own, groups[own_size], overrides)
            competitor_price = money(selected["price"], positive=True)
            current = money(own["current_final_price"], positive=True)
            target = target_price(strategy, competitor_price, current)
            if target is not None:
                if ("min_final_price" in limits and target < money(limits["min_final_price"])) or (
                    "max_change_amount" in limits and abs(target - current) > money(limits["max_change_amount"])
                ):
                    raise PolicyError("LIMIT_EXCEEDED")
            row = {"my_sku": str(own["sku_id"]), "my_design": str(own.get("design", "")), "my_size": own_size,
                   "current_final_price": str(current), "competitor_sku": str(selected["sku_id"]),
                   "competitor_design": str(selected.get("design", "")), "competitor_size": own_size,
                   "competitor_price": str(competitor_price), "competitor_url": selected["url"],
                   "match_method": method, "design_similarity": similarity,
                   "target_final_price": str(target) if target is not None else None,
                   "final_difference": str(round_money(target - competitor_price)) if target is not None else None,
                   "action": "COMPARE" if target is None else "KEEP" if target == current and strategy["direction"] == "down_only" else "CHANGE"}
            if source["mode"] == "repricing" and row["action"] == "CHANGE":
                calculation = create_price_plan(target, direct, subsidy, target_gap=Decimal("0"))
                row.update(recommended_jd_price=str(calculation.jd_price), calculated_final_price=str(calculation.final_price),
                           direct_rate=str(direct), subsidy_rate=str(subsidy),
                           direct_reduction_amount=str(calculation.direct_reduction),
                           government_subsidy_amount=str(calculation.government_subsidy))
                upload_rows.append({"SKUID": row["my_sku"], "京东价": row["recommended_jd_price"]})
            rows.append(row)
    result = {"schema": "jd-shop-price-plan/v1", "status": "READY", "mode": source["mode"],
              "identity": policy["identity"], "policy_revision": policy["revision"], "policy_hash": policy["confirm_token"],
              "input_hash": digest(source), "captured_at": source["captured_at"], "price_context": source["price_context"],
              "strategy": strategy, "activity_model": policy["config"]["activity_model"], "limits": policy["config"]["limits"],
              "activity": source.get("activity") if source["mode"] == "repricing" else None,
              "rows": rows, "upload_rows": upload_rows, "upload_workbook_generated": False,
              "platform_write_performed": False}
    return {**result, "confirm_token": digest(result)}


def save_outputs(result: dict[str, Any], destination: Path, confirm_token: str) -> None:
    if result["mode"] != "repricing":
        raise PolicyError("REPRICING_REQUIRED")
    _save_files(result, destination, confirm_token)


def save_comparison(result: dict[str, Any], destination: Path) -> None:
    if result["mode"] != "comparison" or result["upload_rows"]:
        raise PolicyError("COMPARISON_REQUIRED")
    _save_files(result, destination, result["confirm_token"])


def _save_files(result: dict[str, Any], destination: Path, confirm_token: str) -> None:
    expected = digest({key: value for key, value in result.items() if key != "confirm_token"})
    if confirm_token != expected or result["confirm_token"] != expected:
        raise PolicyError("CONFIRMATION_MISMATCH")
    if destination.exists():
        raise PolicyError("OUTPUT_ALREADY_EXISTS")
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    from build_upload_workbook import build_upload_workbook

    destination.mkdir(parents=True)
    write_json(destination / "plan.json", result)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "SKU比价核验"
    columns = list(dict.fromkeys(key for row in result["rows"] for key in row))
    worksheet.append(columns)
    for row in result["rows"]:
        worksheet.append([row.get(key) for key in columns])
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17365D")
    for values in worksheet.iter_rows(min_row=2):
        for cell in values:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    for index in range(1, len(columns) + 1):
        worksheet.column_dimensions[get_column_letter(index)].width = 24
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    summary = workbook.create_sheet("店铺与策略")
    for key in ("identity", "policy_revision", "policy_hash", "strategy", "activity", "captured_at", "confirm_token"):
        summary.append([key, canonical(result[key])])
    summary.column_dimensions["A"].width = 24
    summary.column_dimensions["B"].width = 100
    workbook.save(destination / "comparison.xlsx")
    check = load_workbook(destination / "comparison.xlsx", read_only=True, data_only=False)
    actual = list(check["SKU比价核验"].values)
    check.close()
    if len(actual) != len(result["rows"]) + 1 or [row[0] for row in actual[1:]] != [row["my_sku"] for row in result["rows"]]:
        raise PolicyError("WORKBOOK_READBACK_FAILED")
    has_upload = bool(result["upload_rows"])
    if has_upload:
        write_json(destination / "upload_rows.json", result["upload_rows"])
        template = Path(__file__).resolve().parents[1] / "assets" / "商品导入价格模板.xlsx"
        build_upload_workbook(template, destination / "upload_rows.json", destination / "price_upload.xlsx")
        uploaded = load_workbook(destination / "price_upload.xlsx", read_only=True, data_only=True)
        actual_rows = list(uploaded.active.iter_rows(min_row=3, max_col=2, values_only=True))
        uploaded.close()
        if [(str(sku), str(money(price))) for sku, price in actual_rows] != [(row["SKUID"], row["京东价"]) for row in result["upload_rows"]]:
            raise PolicyError("UPLOAD_READBACK_FAILED")
    receipt = {"confirm_token": confirm_token, "rows": len(result["rows"]), "upload_rows": len(result["upload_rows"]),
               "upload_workbook_generated": has_upload, "platform_write_performed": False,
               "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in destination.iterdir() if path.is_file()}}
    write_json(destination / "receipt.json", receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["identity", "show", "configure", "rollback", "plan"])
    parser.add_argument("--profile", required=True)
    parser.add_argument("--shop-id")
    parser.add_argument("--shop-name")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--confirm-token")
    parser.add_argument("--output-dir", type=Path)
    arguments = parser.parse_args()
    try:
        identity = read_identity(arguments.profile)
        if arguments.command == "identity":
            result = identity
        else:
            if identity["shop_id"] != arguments.shop_id:
                raise PolicyError("EXPECTED_SHOP_ID_REQUIRED_OR_MISMATCH")
            store = PolicyStore(arguments.state_dir)
            if arguments.command == "show":
                result = store.load(identity)
            elif arguments.command in ("configure", "rollback"):
                if identity["shop_name"] != arguments.shop_name:
                    raise PolicyError("EXPECTED_SHOP_NAME_REQUIRED_OR_MISMATCH")
                if arguments.command == "rollback":
                    if arguments.revision is None:
                        raise PolicyError("ROLLBACK_REVISION_REQUIRED")
                    config = store.load(identity, arguments.revision)["config"]
                elif arguments.legacy and not arguments.config:
                    if store.latest_revision(identity):
                        raise PolicyError("LEGACY_MIGRATION_ONLY_ONCE")
                    config = legacy_config()
                elif arguments.config and not arguments.legacy:
                    config = json.loads(arguments.config.read_text(encoding="utf-8-sig"))
                else:
                    raise PolicyError("EXPLICIT_CONFIG_REQUIRED")
                result = store.commit(identity, config, arguments.confirm_token) if arguments.confirm_token else store.prepare(identity, config)
            else:
                if not arguments.input:
                    raise PolicyError("INPUT_REQUIRED")
                source = json.loads(arguments.input.read_text(encoding="utf-8-sig"))
                result = evaluate(store.load(identity), source)
                if arguments.confirm_token:
                    if not arguments.output_dir:
                        raise PolicyError("OUTPUT_DIRECTORY_REQUIRED")
                    save_outputs(result, arguments.output_dir, arguments.confirm_token)
                    result = json.loads((arguments.output_dir / "receipt.json").read_text(encoding="utf-8"))
                elif arguments.output_dir:
                    if result["mode"] != "comparison":
                        raise PolicyError("CONFIRMATION_REQUIRED_FOR_EXPORT")
                    save_comparison(result, arguments.output_dir)
                    result = json.loads((arguments.output_dir / "receipt.json").read_text(encoding="utf-8"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (PolicyError, ValueError, KeyError, TypeError, OSError, InvalidOperation) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error) if isinstance(error, PolicyError) else type(error).__name__,
                          "platform_write_performed": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
