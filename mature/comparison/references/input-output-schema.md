# Input and Output Schema

京麦多店模式的配置、活动及请求使用 [shop-policies.md](shop-policies.md) 定义的 `jd-shop-policy/v1` 和 `jd-shop-price-plan/v1`。下文是兼容脚本输入，不包含完整店铺身份与确认门禁；不能作为京麦多店正式调价入口。

## Planner input

```json
{
  "expected_competitor_sku_ids": ["competitor-1"],
  "own_skus": [
    {
      "sku_id": "merchant-1",
      "design": "示例图案甲",
      "size": "80*25cm",
      "current_final_price": "14.20"
    }
  ],
  "competitor_skus": [
    {
      "sku_id": "competitor-1",
      "design": "01.示例图案甲",
      "size": "宽80厘米-高25厘米",
      "price": "10.00",
      "url": "https://item.jd.com/competitor-1.html"
    }
  ]
}
```

`expected_competitor_sku_ids` is independently captured from the competitor page. It is not derived from the fetched-record list; otherwise the completeness check proves nothing.

## Direct target price table mode

When the merchant supplies a table of SKU final prices directly (no competitor link), the official 京麦 CLI path accepts `"repricing_mode": "direct_target_table"`. This mode never performs competitor matching, size grouping, or design selection; each merchant SKU's target final price comes only from `target_prices`.

```json
{
  "shop_id": "<真实shopId>",
  "mode": "repricing",
  "repricing_mode": "direct_target_table",
  "captured_at": "<带时区的采集时间>",
  "preflight": {"status": "READY", "purpose": "price", "checked_at": "<本轮门禁时间>"},
  "price_context": "ordinary_single_item",
  "target_prices": {"<商家SKUID>": "<目标到手价>"},
  "own_skus": [{"sku_id": "<商家SKUID>"}],
  "activity": {
    "model": "legacy_direct_subsidy_v1", "direct_rate": "0.15", "subsidy_rate": "0.15",
    "starts_at": "<实际生效时间>", "ends_at": "<实际失效时间>",
    "confirmed_at": "<本轮用户确认时间>", "sku_ids": ["<本批SKU>"]
  }
}
```

`target_prices` 的键集合必须与 `own_skus`/活动 `sku_ids` 完全一致；价格四舍五入到分。到手价反推仍使用 [workflow.md](workflow.md) 的两阶段四舍五入规则，并搜索能精确命中目标价的最高两位小数京东价。规格（尺寸/图案/颜色）在此模式下不参与价格计算，但 CLI 采集仍会重新核验 SKU 归属、在售状态和当前京东价。持久店铺策略可保持 `compare_only`；此模式不受 COMPARISON_ONLY 门禁限制。

## AI match overrides

Required only for merchant SKUs whose exact-size competitor candidates have different prices:

```json
{
  "merchant-1": "competitor-1"
}
```

## Planner outputs

- `comparison_rows.json`: complete audit rows for the detailed workbook, including the current-run `target_gap`.
- `upload_rows.json`: objects with exactly `SKUID` and `京东价`.

Money values are strings with two decimal places to preserve exact decimal semantics across tools.

## Hot-SPU comparison

`hot-own-catalog.json` and `hot-competitor-catalog.json` must both have `status=READY`, an independently enumerated `expected_sku_ids` list, and exactly one `sku_records` row per expected SKU. Every row requires `sku_id`, `normalized_spec`, two-decimal `final_price`, canonical SKU URL, capture time, and `price_evidence.source=jd_detail_network`.

`hot-spu-comparison.json` contains `source_spu_id`, `hot_competitor_spu_id`, `official_sales_rank`, `target_gap`, complete SKU counts, match counts, the competitor's complete SKU records, and one comparison row per own SKU. A matched row includes `hot_competitor_sku_id`, `hot_competitor_final_price`, `suggested_target_final_price`, and `final_price_difference` (`own - competitor`). The default target gap is `0.10`; a different value is valid only when the user 本轮明确指定 it. Unmatched exact sizes remain explicit and do not receive an invented price.

`京东热卖同款SKU比价.xlsx` contains exactly `SKU比价`, `热卖竞品完整SKU`, and `核验摘要`. It displays the current-run target gap and suggested target final price, but it never contains or accompanies a backend upload workbook. The user 必须明确进入改价阶段, 重新运行改价模式 preflight, refresh prices, and provide both rates before upload rows may be generated.

For workbook-source comparison, the first sheet requires `SKUID`, `商品编码`, and `商品名称`. All non-empty rows must belong to one `商品编码`/SPU, every `SKUID` must be unique, and every title must contain a normalizable exact size. The output preserves those source cells and appends `热卖竞品SPU`, `热卖同款对应SKU`, `热卖同款对应SKU到手价`, `本轮目标差价`, `建议目标到手价`, both normalized sizes, matched design, status, method, link, and evidence time. It also adds `热卖竞品完整SKU` and `核验摘要`; it never adds a backend upload sheet.

## Same-product discovery capture

`discovery-captures.json` contains `source`, explicit non-empty `own_shop_names`, and one or more channel captures. The source requires `sku_id`, `spu_id`, `title`, `shop_name`, `product_url`, `normalized_spec`, and a local image path when image comparison is enabled. Its `spu_evidence` must contain `source`, matching `sku_id`, matching `spu_id`, and `captured_at`. Candidate observations retain `sales_text`, `sales_lower_bound`, channel, capture time, display-price evidence, and canonical JD URL. Any observation with `sales_lower_bound` also requires matching `sales_evidence`:

```json
{
  "source": "jd_visible_product_card",
  "sku_id": "90000000000011",
  "product_url": "https://item.jd.com/90000000000011.html",
  "captured_at": "2026-08-30T10:00:00+08:00"
}
```

`candidate-report.json` adds `own_shop_filter.configured` and `source_spu_evidence.proven`. An AI `same` review requires at least two distinct non-empty `evidence_rules` and a non-sensitive `verification_ref`; a user selection uses `confirmation_rules` plus the same reference requirement.

An official image-search capture may also contain `capture_audit` produced by `scripts/jd_image_search_capture.py`. The preferred `build-responses` input stores sanitized `pc_search_image_search` request/response envelopes and excludes signed URLs. Important output fields are `active_sort`, `sort_code`, `function_id`, `declared_result_text`, `declared_result_lower_bound`, exact `result_count`, `api_page_count`, `api_page_size`, `captured_api_pages`, `all_api_pages_captured`, `result_set_complete`, `visible_candidate_count`, `required_rank_window`, `rank_window_complete`, `sales_evidence_complete`, `missing_sales_sku_ids`, and `duplicate_sku_ids`. `result_set_complete` requires every lazy-loaded API page and an exact unique-SKU count. `rank_window_complete` proves that enough unique positions exist; `sales_evidence_complete` separately proves that every candidate has SKU-bound visible sales.

## Exact-spec verification

`product-verifications.json` is keyed by competitor SPU. A verified row contains `status=verified`, entry SKU IDs, selected SKU ID, raw and normalized specifications, two-decimal `final_price`, match method, and `price_evidence` with source, capture time, and the selected SKU URL. Other statuses are `no_exact_size`, `ambiguous`, and `blocked` with a reason.

## Detail SKU evidence

Before creating a verification, save one WebCLI network-detail JSON response for every SKU independently enumerated from the JD specification matrix. The command scripts/jd_detail_evidence.py catalog validates that every response has the same SPU, area, price scene, and complete SKU set. Its sanitized output contains expected_sku_ids and one sku_records row per expected SKU; raw signed request URLs are never copied.

When the SKU title/specification has no numeric size, provide a separate dimension-evidence object keyed by SKU ID:

    {
      "90000000000011": {
        "normalized_spec": "80x47x40cm",
        "source": "jd_visible_product_image",
        "captured_at": "2026-08-30T11:00:00+08:00",
        "local_image_path": "working/90000000000011.png",
        "note": "Visible image prints 80cm x 47cm x 40cm."
      }
    }

The source must be jd_visible_product_image, jd_detail_specification, or user_confirmed_image. Dimensions must be visibly stated; image proportions are not evidence. Two-dimensional and three-dimensional keys are never equal.

A visibly labeled non-comparable product form can be retained without inventing a dimension:

    {
      "90000000000012": {
        "classification": "non_comparable_variant",
        "source": "jd_sku_text",
        "captured_at": "2026-09-01T11:00:00+08:00",
        "note": "Visible SKU text identifies a desktop display variant."
      }
    }

This classification is accepted only when the SKU text explicitly identifies a supported non-comparable form such as `摆台`; its normalized size is empty and it never enters exact-size matching. The specification matrix defines the current SPU SKU set. Stock maps must cover every matrix SKU, while extra stock-map IDs from other SPUs are ignored rather than added to the catalog.

## Market report

`same-product-report.json` contains `status`, `ranking_basis`, `ranking_label`, `source`, `same_product_list`, `top_same_spec`, `statistics`, `blocking_reasons`, and machine-readable `issues`. `ranking_basis` is `jd_official_sales_sort_rank_psort_3` only after a complete trusted official audit; otherwise it is `jd_visible_sales_lower_bound`. Ranked rows expose `official_api_rank`; missing numeric sales remain null and display as `京东未展示`. The list may expose `display_price_observations` for audit, but 搜索展示价不得参与 statistics. `statistics` contains `sample_count`, `top_limit`, `minimum_final_price`, and `average_final_price`; prices and `top_same_spec` are present only when status is `READY`.

Status values are `READY`, `PARTIAL`, `ACTION_REQUIRED`, and `BLOCKED`. Stable issue codes include `OWN_SHOP_FILTER_NOT_CONFIGURED`, `SOURCE_SPU_UNPROVEN`, `DISCOVERY_RESULT_SET_INCOMPLETE`, `DISCOVERY_RANK_WINDOW_INCOMPLETE`, `PAGE_SALES_EVIDENCE_REQUIRED`, and `SAME_PRODUCT_EVIDENCE_INSUFFICIENT`. If user action and blockers coexist, `ACTION_REQUIRED` takes precedence for the current run; rerun after the action instead of treating it as proof that other checks passed.
