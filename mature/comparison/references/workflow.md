# End-to-End Workflow

## 京麦店铺流程优先

京麦多店按 [jingmai-api.md](jingmai-api.md) 执行：官方身份及本店数据 → 店铺配置加载 → 本轮竞品证据与活动核验 → 确切策略计划与只读预检 → 人工确认 → 价格专用 PATCH → 申请单和线上回读。配置仍按 [shop-policies.md](shop-policies.md) 管理；用户明确“只导表”才走文件路径。以下步骤 0-9 是历史浏览器/工作簿兼容流程，其当前价 Excel、两比例和固定差价要求不得套到默认 API 路径或新店。已配置店铺直接沿用自己的长期策略。

## 0. Choose one mode

- **同品市场分析**: start from a JD front-end SKU/link, run 京东页面可见识图 plus 标题/规格搜索, output a 销量降序 same-product list and default 同规格TOP10 最低价/平均价. Follow `competitor-discovery.md`.
- **热卖竞品SPU比价与改价**: after fixing one official sales-ranked same-product SPU, independently capture the complete own and competitor SKU catalogs and match exact sizes once. Stop after the comparison workbook unless the user explicitly asks to continue into repricing.
- **直接竞品改价**: start from a merchant workbook and an already selected competitor link, use the same strict capture/matching pipeline, then follow steps 1-9 below.

搜索展示价不得参与统计 or repricing. If market analysis produces a selected competitor, 重新运行价格模式 preflight before step 3.

For discovery, use `python scripts/browser_capture.py preflight --provider webcli --profile <context> --require-image-tools`. The optional explicitly configured merchant image-search channel is valid only when `mode=upstream` and `upstreamConfigured=true`; `fixture` is never real image-search evidence.

For hot-SPU comparison, use the same discovery gate. Do not ask for promotion rates. Capture both catalogs with `scripts/webcli_jd_detail_capture.py`, then run:

```bash
python scripts/hot_spu_comparison.py \
  --source-catalog working/hot-own-catalog.json \
  --competitor-catalog working/hot-competitor-catalog.json \
  --official-rank 1 \
  --json-output working/hot-spu-comparison.json \
  --output outputs/京东热卖同款SKU比价.xlsx
```

If one exact-size competitor group contains different prices, provide an explicit `--overrides` JSON mapping. The comparison stage defaults to `--target-gap 0.10`; use another value only when the user 本轮明确指定 it. This stage displays a suggested target final price but creates only the comparison workbook.

The user 必须明确进入改价阶段 before any upload output. A continuation must 重新运行改价模式 preflight, refresh competitor price evidence, provide the current-price workbook, and reconfirm both rates. A comparison-stage READY result never authorizes repricing.

When the user supplies an own-SKU workbook with `SKUID`, `商品编码`, and `商品名称`, use all workbook rows as the own-SPU truth instead of replacing them with a single entry-SKU catalog. Require exactly one source SPU, parse every title's exact size, preserve the original columns, and run:

```bash
python scripts/hot_spu_workbook_comparison.py \
  --source-workbook inputs/own-spu.xlsx \
  --competitor-catalog working/hot-competitor-catalog.json \
  --selection-evidence working/selection-evidence.json \
  --json-output working/hot-spu-workbook-comparison.json \
  --output outputs/京东热卖同款SKU比价.xlsx
```

Map by the explicit variant/design label nearest the size token plus exact normalized size. Generic product phrases earlier in the title, such as a series/category term that is also a competitor variant label, must not override the trailing merchant variant. If design-and-size candidates have different prices, require an explicit override and stop without output otherwise.

Before market statistics, configure `own_shop_names`, prove the source `spu_id` with SKU-bound `spu_evidence`, normalize every lazy-loaded official image-search API page through `jd_image_search_capture.py build-responses`, and use `webcli_jd_search_capture.py` for durable title/specification fallback capture. Retain only `jd_visible_product_card` numeric sales evidence, and require at least two explicit same-product evidence rules plus a non-sensitive `verification_ref`. The market report exposes `issues` and uses `READY`, `PARTIAL`, `ACTION_REQUIRED`, or `BLOCKED`; only `READY` may publish the default TOP10 or explicitly requested TOP20 prices. A complete official `psort=3` audit may instead publish by `official_api_rank`; missing numeric sales stay `京东未展示`, while declared but unbound sales evidence still blocks.

## 1. Confirm inputs and rates

Ask for the direct-reduction rate and government-subsidy rate every time. Confirm the merchant workbook and competitor URL are accessible. Use the first sheet only when the user explicitly says so; otherwise identify the intended sheet from headers and ask only when ambiguity remains.

## 2. Pass the external browser/environment gate

The parent launcher supplies a sanitized environment and an absolute `HEIDENG_MERCHANT_HOME`. Use externally installed WebCLI directly, with its already configured Browser Bridge profile:

```bash
python scripts/browser_capture.py preflight --provider webcli --profile <context> --require-image-tools
```

`READY` here proves only current read-only browser capability/account verification, never repricing authority. Do not auto-install tools or switch to an employee/private fallback. Missing installation/bridge/account identity is a genuine blocker. Only task-owned sessions are opened and closed. Repricing must separately refresh source/activity evidence and pass the existing official API plan/confirmation/readback gates. The optional image-search bridge is disabled until explicitly merchant-configured and healthy.

## 3. Extract merchant SKUs

Read SKU ID, title/specification, current final price, and any product link. Extract the pattern/design and size from the title's trailing variant text. Normalize `*`, `×`, and `x` dimensions to `WIDTHxHEIGHT`.

Reject blank or duplicate merchant SKU IDs and rows without a numeric current final price.

## 4. Capture the competitor catalog

Open the JD product page in the available signed-in browser. Capture the complete SKU ID list from page state or network responses. Then retrieve every SKU independently and record:

- `sku_id`
- real `design`/color field
- real `size` field
- current final price under one consistent promotion context
- SKU-specific product URL

For the current JD desktop page, capture the GET pc_detailpage_wareBusiness response through WebCLI. Match the request-body SKU to the opened SKU and reject the adjacent OPTIONS request or stale cache entries. Feed one saved response per SKU to scripts/jd_detail_evidence.py catalog; do not commit raw responses because their URLs contain short-lived signatures and session identifiers.

Use SKU text dimensions first. If the text only contains labels such as 大号 or 加长款, accept image/specification fallback only when the visible JD evidence explicitly prints every normalized dimension. Record that evidence per SKU; never estimate dimensions from image shape.

Do not zip two arrays by index. The page's SKU list order and option-button order are not a specification mapping.

## 5. Prove completeness

The fetched SKU ID set must equal the page's expected SKU ID set. Every record must have a real size, design, price, and URL. Stop if authentication, CAPTCHA, throttling, or partial responses prevent proof.

## 6. Match variants

Use exact normalized size first.

- One price within that size: choose the closest design name for the audit link; price does not depend on design.
- Multiple prices within that size: inspect normalized names and available product images. Choose the most similar design and save the explicit mapping in an overrides JSON object, e.g. `{"merchant-sku": "competitor-sku"}`.

Do not substitute a lowest-price policy for AI design judgment.

## 7. Run deterministic validation and inversion

Prepare input JSON according to `input-output-schema.md`, then run:

```bash
python scripts/jd_price_adjustment.py plan \
  --input working/catalog.json \
  --direct-rate 15 \
  --subsidy-rate 15 \
  --target-gap 0.10 \
  --overrides working/match-overrides.json \
  --output-dir working/results
```

Omit `--overrides` only when no exact-size group has multiple prices. Omit `--target-gap` when the user did not request another value; the default target gap is `0.10`. Exit code `2` means final outputs must not be generated.

## 8. Build workbooks

Use `spreadsheets:Spreadsheets` and its bundled runtime.

- Create a detailed comparison workbook from `comparison_rows.json` with filters, frozen headers, two-decimal money formats, source URLs, and visible exception/status columns.
- Build the upload workbook with the dependency-free helper, which preserves row 1 and row 2 and writes only columns A:B:

```bash
python scripts/build_upload_workbook.py \
  --rows working/results/upload_rows.json \
  --output outputs/京东价批量修改上传表.xlsx
```
- Do not add helper sheets or columns to the upload workbook.

## 9. Final gates

Reopen the exported XLSX files and verify:

- output row count equals merchant SKU count;
- all merchant SKU IDs are unique and present once;
- every matched size equals the real competitor size;
- every upload JD price equals its detailed-table recommendation;
- every recalculated final price equals competitor price minus the current-run target gap; the default is `0.10`;
- no `#REF!`, `#VALUE!`, `#N/A`, `#DIV/0!`, `#NAME?`, or `#NUM!` exists;
- the upload workbook has exactly one sheet and two used columns;
- all sheets render legibly.

If any gate fails, do not deliver the upload workbook.
