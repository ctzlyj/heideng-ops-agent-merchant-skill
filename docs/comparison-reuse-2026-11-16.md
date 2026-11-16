# Bounded mature comparison reuse — 2026-11-16

## Source and immutable selection

- Repository: `ctzlyj/jd-competitor-price-adjustment-skill`.
- Released/audited Git HEAD: `43bdf6790fe3c8a5b89c217edcaefabf670cbc2c`; version `1.0.0`.
- MIT, copyright (c) 2026 ctzlyj; the complete upstream LICENSE is retained.
- Audited source Git status was clean. The installed read-only source directory has no Git metadata; its text differs from audited blobs only by installation CRLF conversion. Selection checked content against the audited commit, but **copied raw `git show <commit>:<path>` bytes**, not installed/dirty-tree bytes. No whole personal directory, runtime configuration, credentials, installer or private package download was copied.
- `mature/comparison/provenance.json` follows the parent contract: `schemaVersion`, `repository`, `upstreamCommit`, `upstreamVersion`, `license`, `files`, `entrypoints`. Every file in this bundle except provenance itself is included, including LICENSE, references, requirements, and the tracked empty two-header-row upload template. `sha256` is the exact destination byte hash. `upstreamSha256` is the Git blob byte hash; `adapted=false` requires equality. Explicit unchanged/adapted mappings are included. Only new `merchant_runtime.py` and inferred `requirements.txt` have null upstream hashes (there is no upstream requirements file); they still have exact destination hashes and are not represented as upstream code.
- The parent must validate the manifest/allowlist **before launching**, preserve bytes without CRLF normalization, and supply its existing source launcher/sanitized environment. This child did not modify CLI, registry, routes, distribution, or parent authorization behavior.

## Mature implementation actually reused

Eleven original Python implementation files remain byte-for-byte unchanged: `jd_price_adjustment.py`, `same_product_market.py`, `competitor_discovery.py`, `jd_detail_evidence.py`, `jd_image_search_capture.py`, `image_similarity.py`, `hot_spu_comparison.py`, `hot_spu_workbook_comparison.py`, `build_market_workbook.py`, `build_upload_workbook.py`, and `webcli_jd_search_capture.py`.

This retains complete-SKU evidence validation, exact-spec comparisons, explicit design overrides where same-spec candidates have multiple prices, local image hashing/histogram similarity, sales/SPU grouping, official-rank and uncertain-rank gates, default TOP10/explicit TOP20 verified-price statistics, Decimal half-up monetary inversion, workbook production, and comparison-versus-repricing separation. Search display prices remain excluded from publishable market statistics. Non-READY reports clear TOP rows/minimum/average.

`store_pricing.py` and `jingmai_api.py` retain their mature policy revision/confirmation, exact plan hash, identity/activity/baseline checks, price-only PATCH, durable SUBMITTING/unknown-outcome state, application and online readback, and no-replay recovery logic. Only executable lookup and runtime paths were adapted. No replacement business dispatcher or state machine was introduced.

## Thin boundaries, no employee dependencies

- `browser_runtime.py`: externally installed **WebCLI directly**, argv lists with `shell=False`, UTF-8, background execution and the mature unknown-outcome error semantics. No tool alias registry, fallback supplier installer, personal skill path, or private npm download. On Windows, an externally installed npm WebCLI PowerShell shim is launched with system PowerShell `-File`; alternatively the parent can supply an explicit native argv prefix in `HEIDENG_WEBCLI_COMMAND_JSON`. Arguments and stdin are passed intact.
- `browser_capture.py`: keeps the original capability/account gate and task-session cleanup; only WebCLI is supported. No implicit Playwright/private fallback. Existing connected external Browser Bridge contexts must be configured by the merchant/host. A missing tool, bridge, profile, identity or login is a blocker, not permission to authenticate/install automatically.
- `merchant_runtime.py`: a small path/executable boundary, **not** a business runtime. Absolute `HEIDENG_MERCHANT_HOME` is mandatory. Policies default to `<home>/comparison/stores`; browser cwd to `<home>/comparison/browser-runtime`; capture checkpoints to `<home>/comparison/capture-runs`; API execution to `<home>/comparison/api-runs`. Explicit private state paths must resolve within the supplied home and outside the installed bundle. Direct capture CLI checkpoints are checked before browser transport. The existing mature checkpoint account/scope/freshness algorithm is retained.
- Official executable discovery uses `JDO_CLI_PATH` or externally installed `jdo-cli` on PATH, not a guessed personal directory. `JDO_HOME` is mandatory for official subprocess access and must be inside the supplied merchant home. The parent supplies the sanitized environment; this child does not copy credentials or reimplement environment sanitization.
- Direct dependencies inferred from the selected imports are only Pillow and openpyxl. Their own licenses still apply; the upstream MIT license does not relicense dependencies. Requirements are declarative only, never automatically installed.

### Actual model/service audit

No company model SDK, company image-generation code or company model key exists in the selected algorithm code. `image_similarity.py` uses Pillow locally. AI review and multi-price design overrides are supplied evidence, not an embedded inference provider. Missing reviews remain gated; no unconfigured model is claimed usable.

The optional `authorized_image_search.py` was a generic HTTP bridge hardwired to localhost. Its validation algorithms remain unchanged, but the service boundary now fails with `AUTHORIZED_IMAGE_SEARCH_UNCONFIGURED` unless a merchant explicitly supplies `HEIDENG_COMPARISON_IMAGE_SEARCH_ORIGIN`. Upstream health must still assert real configured upstream data; fixture/discovery prices cannot become TOP10 price evidence. This migration does not configure, authenticate or validate any external model/service.

## Exact original entrypoints and pass-through commands

Bundle absolute root for this checkout:
`C:\Users\caotong.888\.codex\worktrees\merchant-mature-reuse\黑灯运营智能体商家版\mature\comparison`

The parent should pass original argv unchanged (no invented business command):

| Entry under bundle | Original command(s) | Purpose |
| --- | --- | --- |
| `scripts/same_product_market.py` | `build` | **Recommended comparison/TOP10 default**; consumes verified discovery/evidence JSON |
| `scripts/jd_price_adjustment.py` | `plan` | Real CLI, but legacy fixed-gap two-rate planning/export, not market discovery |
| `scripts/competitor_discovery.py` | `report`, `select` | Review/gate discovery candidates; explicit competitor selection |
| `scripts/jd_detail_evidence.py` | `catalog`, `verify` | Parse complete SKU-bound detail responses; exact-spec verification |
| `scripts/jd_image_search_capture.py` | `build`, `build-responses` | Normalize supplied visible image-search evidence |
| `scripts/image_similarity.py` | `batch` | Local real-image similarity |
| `scripts/browser_capture.py` | `preflight`, `detail`, `search` | Read-only original browser workflow, adapted transport |
| `scripts/browser_runtime.py` | `invoke`, `session` | Thin transport/session utility, not a business dispatcher |
| `scripts/webcli_jd_detail_capture.py` | flags only | Original direct detail capture |
| `scripts/webcli_jd_search_capture.py` | flags only | Original title/specification capture |
| `scripts/hot_spu_comparison.py` | flags only | Complete own/competitor catalog comparison workbook |
| `scripts/hot_spu_workbook_comparison.py` | flags only | Own workbook truth + competitor catalog comparison |
| `scripts/build_market_workbook.py` | flags only | Produce same-product/TOP10/summary workbook |
| `scripts/build_upload_workbook.py` | flags only | Fill original tracked price-upload template |
| `scripts/store_pricing.py` | `identity`, `show`, `configure`, `rollback`, `plan` | Original shop policy/optional export workflow |
| `scripts/jingmai_api.py` | `collect`, `prepare`, `execute`, `status`, `rollback-plan` | Original official confirmation/readback workflow |

`authorized_image_search.py` and `merchant_runtime.py` are importable helpers, not invented CLI entrypoints. All sixteen listed entrypoints passed real subprocess `--help` and import tests from a temporary cwd with no authentication/configuration. Existing `same_product_market.py build` deliberately writes a gated non-READY report and returns CLI success; consumers must inspect its `status`/`issues`, never infer READY from process exit alone.

### Runnable offline examples

The parent launcher should normally run these exact scripts after provenance verification. Direct examples below use a merchant demo home and evidence already collected/reviewed; they do not acquire authorization or call a model:

```powershell
$env:HEIDENG_MERCHANT_HOME = 'C:\MerchantData\comparison-demo'
$bundle = 'C:\Users\caotong.888\.codex\worktrees\merchant-mature-reuse\黑灯运营智能体商家版\mature\comparison'
python -B "$bundle\scripts\same_product_market.py" --help
python -B "$bundle\scripts\same_product_market.py" build --discovery "$env:HEIDENG_MERCHANT_HOME\comparison\discovery.json" --verifications "$env:HEIDENG_MERCHANT_HOME\comparison\verified.json" --output "$env:HEIDENG_MERCHANT_HOME\comparison\report.json"
python -B "$bundle\scripts\build_market_workbook.py" --report "$env:HEIDENG_MERCHANT_HOME\comparison\report.json" --output "$env:HEIDENG_MERCHANT_HOME\comparison\market.xlsx"
python -B "$bundle\scripts\jd_price_adjustment.py" plan --input "$env:HEIDENG_MERCHANT_HOME\comparison\catalog.json" --direct-rate 0.15 --subsidy-rate 0.15 --overrides "$env:HEIDENG_MERCHANT_HOME\comparison\overrides.json" --output-dir "$env:HEIDENG_MERCHANT_HOME\comparison\legacy-plan"
```

The 0.15 rates above are explicit examples, not a new shop default. The legacy planner creates local upload JSON only; it does not authorize an official write. Never dispatch `jingmai_api.py execute` without the actual current plan's exact human-confirmed token and shop scope. `status` is the original readback-only recovery path; unknown writes must not be replayed by choosing another tool/run directory.

## Verification and remaining blockers

- Test-first initial run: 14 tests, **11 failures and 2 errors**, due to absent migration/manifest; no business implementation had been copied yet. One initial canonical-spec test expectation was corrected to the actual upstream 2D key (`80x40`); upstream code was not changed to satisfy an invented API.
- A direct-checkpoint escape test was separately observed failing before its boundary fix; the official JDO namespace regression also failed before its boundary fix. Both pass after thin-boundary adaptation.
- Final command: `python -B -m unittest discover -s tests -p test_mature_comparison.py -v` — **20 tests passed in 13.997 seconds, exit 0**. Tests exercise actual copied algorithms, complete/missing catalogs, overrides, dimensions, verified-price TOP10, uncertain/source/own-shop gates, actual Pillow images, real XLSX creation/readback, real original `build`/`plan` subprocess output, all sixteen subprocess help/import entrypoints, byte hashes, external-process argv/stdin/namespace behavior, disabled optional bridge, and mature confirmation/readback/unknown-write no-replay behavior using an explicitly offline client fixture.
- Final independent byte audit: **27/27 current destination hashes exact; all recorded upstream hashes match clean audited Git HEAD; 14 files byte-identical to upstream; 18 Python modules parse; 16 CLI entries recorded**. The comparison bundle is frozen for parent verification; no shared builder was run.
- Real installed external WebCLI smoke: `python -B <bundle>\scripts\browser_runtime.py invoke -- --help` returned WebCLI's actual help via the direct adapter with a temporary supplied merchant home. This did **not** initialize a browser or authenticate a shop. No `doctor`/live capture/auth/model/official shop write was run.
- Parent route/registry integration and sanitized launcher/provenance enforcement remain parent responsibilities; no shared file was changed here.
- Live Browser Bridge/account login, real SKU/rank/price evidence, review/model provider configuration, exact shop authorization and future confirmed official write/readback are **unverified**, intentionally outside this task. Offline success does not prove live operational readiness.
- Legacy repricing's upstream `normalize_size` is permissive and 2D-oriented; the stronger detail-evidence parser preserves 2D versus 3D keys. This migration does not silently expand legacy repricing/category/spec support or rewrite that mature algorithm; arbitrary 3D/category repricing needs a separately scoped upstream-supported solution.
- No commit, push, release, auto-install or live operation was performed. Only this bundle, `tests/test_mature_comparison.py`, and this document were edited; unrelated concurrent changes were left alone.
