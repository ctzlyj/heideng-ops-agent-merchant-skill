# JD Same-Product Discovery and Market Analysis

## Preconditions

Run `scripts/browser_capture.py preflight --provider auto --require-image-tools` and continue only from the latest `READY` gate. Follow the parent merchant migration guide (`docs/comparison-reuse-2026-11-16.md`): prefer the existing authenticated WebCLI, otherwise an independently verified provider. Stop on login, CAPTCHA, risk control, incomplete page state or contradictory evidence, not merely because a particular optional tool is absent. Existing explicit WebCLI commands below remain compatible and now use the maintained safe transport.

## Source Capture

Open the public JD source item and capture the selected SKU, title, shop, selected raw specification, normalized dimension, product URL, main-image URL, and a local copy of the public main image. Configure at least one explicit `own_shop_names` value. Prove the source SPU with `spu_evidence` containing an allowed source (`jd_visible_page` or `jd_detail_network`), the same `sku_id`, the same `spu_id`, and `captured_at`; a merely asserted SPU is not enough. Dimensions must be parsed from actual specification text and normalized before comparison.

## Candidate Channels

1. Try 京东页面可见识图, including visible 识同款、图片搜索 or 拍照购 controls. Record `available`, `unavailable`, or `blocked`; absence is not a successful image-search result.
2. Run 标题/规格搜索 using the product title and normalized size tokens.
3. Optionally query an explicitly configured merchant `HEIDENG_COMPARISON_IMAGE_SEARCH_ORIGIN` through `authorized_image_search.py`. Accept only `mode=upstream` and `upstreamConfigured=true`; reject fixture data.

Across channels, capture canonical JD item URL, SKU, SPU if proven, title, shop, image, sales text/lower bound, ad flag, channel, page URL, and capture time. Every observation carrying `sales_lower_bound` must also carry `sales_evidence` with source `jd_visible_product_card`, the same SKU, its canonical JD item URL, and capture time. Exclude advertisements, source SKU/SPU, and configured own shops. Deduplicate SKU observations without discarding provenance.

Record the title/specification search role truthfully: use `supplement` when it accompanies working visible image search, `independent` when it makes no claim about image-search availability, and `fallback` only when visible image search was actually unavailable. A supplement or independent search must not carry degradation fields.

When visible image search is absent or only opens the JD Shopping Assistant download introduction, record `VISIBLE_IMAGE_SEARCH_UNAVAILABLE` and the observed reason; never label the fallback as image search. Use the durable title/specification collector with the exact WebCLI profile that passed preflight:

    python scripts/webcli_jd_search_capture.py ^
      --profile <context-id> ^
      --keyword "<title and exact-size terms>" ^
      --source working\source.json ^
      --own-shop "<configured own shop>" ^
      --search-role fallback ^
      --image-search-issue VISIBLE_IMAGE_SEARCH_UNAVAILABLE ^
      --image-search-observation JD_ASSISTANT_DOWNLOAD_INTRO_ONLY ^
      --output working\captures.json

The collector supports the current React `goodsCardWrapper[data-sku]` cards and legacy cards, accumulates virtualized cards by SKU, strips search and tracking queries from the saved page URL, and emits a document accepted directly by `competitor_discovery.py report`. It never saves the WebCLI profile, cookies, headers, tokens, or raw page HTML. A visible review count, “人看过”, or a card-wide text fragment containing multiple metrics is not sales evidence.

## Image Review

Download only publicly visible source and candidate images. Run `image_similarity.py batch` on local paths. Use aHash, dHash and RGB histogram values to prioritize candidates; never use a threshold as automatic same-product proof. AI records `same`, `different`, or `uncertain` with confidence, at least two explicit `evidence_rules`, and a non-sensitive `verification_ref`. Explicit user confirmation must likewise provide at least two `confirmation_rules` and a non-sensitive `verification_ref`. Only a high-confidence `same` or explicit user confirmation satisfying this evidence contract enters the market list.

## Sales and SPU Grouping

Group all confirmed entry SKUs by explicit SPU evidence. With a complete official `psort=3` audit, use the lowest `official_api_rank` per SPU and keep title/specification-only candidates outside that official ranking pool. Otherwise use the maximum verified `sales_lower_bound` from retained observations and order in 销量降序; missing sales then block publication. Never infer SPU from adjacency or array position.

For the official image-search iframe, capture the `pc_search_image_search` response that drives every card. One visible UI page can contain multiple API pages: for a 30-row page size, scrolling the first UI page can load API page 2 at result offset 31, while the next UI page can start at API page 3 / offset 61. Save only a sanitized envelope containing `request_body.page`, `request_body.s`, `request_body.psort`, response `pageInfo`, selected sort, and the required `wareList` card fields; never retain the signed URL or account/session query fields. Normalize all response pages before merging channels:

    python scripts/jd_image_search_capture.py build-responses ^
      --input working\image-search-responses.json ^
      --output working\image-search-capture.json

The helper accepts only the official `jd-pc-search-image-pro.pf.jd.com` page, function `pc_search_image_search`, request `psort=3`, and matching response sort `3`. It validates every API page, expected `s` offset, exact `resultCount`, page size, unique SKU count, and any equality between `totalSales` and visible `commentSalesFloor` text. It parses values such as `已售1.2万+`, binds numeric evidence to the exact SKU URL, and separates `result_set_complete`, `rank_window_complete`, and `sales_evidence_complete`. A manual DOM snapshot with an approximate count such as `80+` cannot prove the full result set. “人看过”、评价数, DOM position, and active-sort styling never become sales evidence. If the complete trusted response omits numeric sales, preserve `sales_lower_bound=null` and `sales_text=京东未展示`; the official `api_rank` may still order that official result pool, but must never be presented as a numeric sale.

## Exact-Spec Verification

Process candidates in the report's explicit ranking order: complete official `psort=3` API rank when available, otherwise verified visible-sales lower bound. For each SPU, independently enumerate the complete SKU ID set and fetch each SKU's real specification, design, final price, and SKU URL. Exact normalized size equality is mandatory. If an exact size has multiple prices, AI or the user must select the closest design and save an explicit override. Search display price and `authorized_price_cents` remain audit-only.

Use WebCLI network evidence from the product page's pc_detailpage_wareBusiness request. The chosen network entry must be GET, and its request-body skuId must equal both the opened URL SKU and body.pageConfigVO.skuid; ignore the adjacent OPTIONS request and stale entries from a reused Chrome tab. Keep raw signed responses only in temporary working storage and never commit them.

Prefer the fixed-profile helper for live collection. `--seed-only` captures one trusted SKU plus the complete option matrix for early product-form rejection; omit it only after the SPU remains eligible and every matrix SKU must be fetched:

    python scripts/webcli_jd_detail_capture.py ^
      --profile <context-id> ^
      --entry-sku <sku-id> ^
      --seed-only ^
      --output working\seed.json

The helper closes its temporary WebCLI tab on success or failure and emits only sanitized SKU/SPU/specification/price evidence. Login, CAPTCHA, risk control, SKU mismatch, SPU mismatch, or incomplete matrix evidence stops the run.

Save one WebCLI network-detail JSON file for every independently enumerated SKU, then build a sanitized catalog:

    python scripts/jd_detail_evidence.py catalog ^
      --responses working\detail-responses\*.json ^
      --dimension-evidence working\dimension-evidence.json ^
      --output working\catalog.json

The parser treats colorSizeList as the current SPU's complete SKU set. canAddCartMap, stockInfo, and skuBatchPurchaseMap must each cover every matrix SKU, but may contain extra IDs from other SPUs; those extras never expand the current catalog. Every expected matrix SKU must have exactly one response captured under the same area and price scene.

Prefer numeric dimensions in the selected SKU specification text. Normalize labeled forms such as `宽60厘米X高120厘米`, `宽度60厘米×高度120厘米`, and suffix labels such as `60厘米宽×120厘米高` before exact comparison. If the text only says 大号、加长款 or an age range, dimension-evidence.json must explicitly record dimensions printed on a visible JD product image or specification panel, its capture time, and the image URL or local path. Never estimate dimensions from proportions. Preserve three-dimensional sizes such as 80x47x40cm; do not collapse them into two dimensions. When the SKU text itself clearly identifies a different product form such as `摆台`, record `classification=non_comparable_variant`, `source=jd_sku_text`, capture time, and a note. Keep that SKU in the catalog with an empty normalized size so it cannot match the source hanging-picture size.

Create the exact-spec SPU verification only from the complete catalog:

    python scripts/jd_detail_evidence.py verify ^
      --catalog working\catalog.json ^
      --source-spec 80x47x40cm ^
      --entry-sku 12345678901234 ^
      --selected-sku 12345678901234 ^
      --output working\verification.json

If exact-size SKUs have different prices, --selected-sku is mandatory and records the explicit AI/user choice. A visible finalPrice is preferred; an explicitly labeled bybtPrice is accepted only when it exactly equals the page's primary price field. In a proven no-discount scene, the page's current `price.p` must equal the sole `jdPrice`; `price.op` is only an original/reference price and may be higher. Contradictory or missing current-price evidence blocks the product.

## TOP10 and Output

Collect up to 20 verified exact-size samples in sales order. Proven high-confidence different and no_exact_size products are skipped. If an uncertain, unreviewed, ambiguous, or blocked candidate could still enter the first 20, set the report to BLOCKED; 最低价 and 平均价 must remain empty. Otherwise run same_product_market.py build and build_market_workbook.py.

The report always includes `issues`. Use these stable gate codes:

- `OWN_SHOP_FILTER_NOT_CONFIGURED` → `ACTION_REQUIRED`.
- `SOURCE_SPU_UNPROVEN` → `BLOCKED` unless a simultaneous user-action issue takes precedence.
- `PAGE_SALES_EVIDENCE_REQUIRED` alone → `PARTIAL`.
- `DISCOVERY_RESULT_SET_INCOMPLETE` alone or with other discovery completeness issues → `PARTIAL`.
- `DISCOVERY_RANK_WINDOW_INCOMPLETE` alone or together with missing page sales → `PARTIAL`.
- `SAME_PRODUCT_EVIDENCE_INSUFFICIENT` → `BLOCKED`.

When multiple issues exist, `ACTION_REQUIRED` takes precedence so the user can complete the required action, then the rerun exposes any remaining blocker. Only `READY` can publish `top_same_spec`, minimum price, and average price.

The default workbook contains `同品列表`, `同规格TOP10`, and `统计摘要`. Pass `--top-limit 20` only when the user explicitly requests the legacy wider window. 搜索展示价不得参与统计. Market mode never creates the backend upload workbook. Selecting a competitor for repricing requires 重新运行价格模式 preflight.
