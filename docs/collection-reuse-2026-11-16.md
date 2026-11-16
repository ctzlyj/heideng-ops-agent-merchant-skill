# Bounded MIT collection reuse — 2026-11-16

## Result and scope

This is a **bounded source migration, not a declaration that full live collection is ready**.
Offline preparation, price/SKU contracts, checkpoints, package construction, independent
verification and delivery are executable using the actual mature upstream functions.
The per-product native SDK/XHR collector is preserved behind a thin externally supplied
browser boundary. No live login, new authorization, business-data retrieval, price request,
shop mutation, publication or credential migration was performed.

Edits are limited to `mature/collection/**`, `tests/test_mature_collection.py`, and this document.
No changes to parent CLI, registry, distribution, launcher or existing browser modules.
No commits or pushes. Existing unrelated worktree changes are not part of this migration.

## Source selection / raw-byte provenance

- Repository: `ctzlyj/jd-hot-link-collector`.
- Upstream commit: `90ef8dfd8455848d539d22560ae26ba8bac52e2a`.
- Upstream version: `1.0.4`, verified in the pinned `SKILL.md` blob.
- License: MIT, original `Copyright (c) 2026 ctzlyj`; the complete original LICENSE is retained.
- The requested source alias resolves to the `.joycode` checkout. Its working tree is READ ONLY.
- Source `git status --short` reported an unpublished change to
  `scripts/batch_driver/stage_pending_materials.py`. That script is **not selected**.
- Every selected file was obtained with `git show <pinned-commit>:<path>`, never by copying
  working-tree files. HEAD was checked against the pin. No untracked or runtime files were read
  into the package. No browser contexts, user tables, checkpoints, caches, outputs or credentials
  are included.
- 28 selected tracked files: 19 byte-identical, 9 adapted. The provenance manifest itself is
  the only file under `mature/collection` not listed in its `files` map.
- `provenance.json` follows the parent contract exactly: `schemaVersion: 1`, `repository`,
  `upstreamCommit`, `upstreamVersion`, `license`, `files`, `entrypoints`.
  Each file record has `upstreamSha256` (original Git blob bytes), `sha256` (final file bytes),
  and `adapted` (whether bytes differ). The builder must preserve raw bytes, including BOM and
  line endings; the parent verifies the final hashes before launch. Do not normalize source text
  or silently regenerate this manifest during launch.

### Exact selected files (relative to `mature/collection`)

- `LICENSE` — byte-identical
- `requirements.txt` — byte-identical
- `references/price-and-sku-contract.md` — byte-identical
- `references/package-contract.md` — byte-identical
- `references/rate-limit-and-recovery.md` — byte-identical
- `scripts/collector_guard.py` — byte-identical
- `scripts/package_contract.py` — byte-identical
- `scripts/workbook_writer.py` — byte-identical
- `scripts/checkpoint_status.py` — byte-identical
- `scripts/media_evidence.py` — byte-identical
- `scripts/media_guard.py` — byte-identical
- `scripts/jpeg_cache.py` — byte-identical
- `scripts/resume_policy.py` — byte-identical
- `scripts/asset_paths.py` — adapted
- `scripts/package_live.py` — adapted
- `scripts/verify_batch.py` — adapted
- `scripts/prepare_batch.py` — adapted
- `scripts/deliver_batch.py` — adapted
- `scripts/variant_queue.py` — byte-identical
- `scripts/variant_bridge.mjs` — adapted
- `scripts/request_policy.mjs` — byte-identical
- `scripts/browser_worker.mjs` — byte-identical
- `scripts/native_page.mjs` — byte-identical
- `scripts/runner_lock.mjs` — byte-identical
- `scripts/collection_policy.mjs` — adapted
- `scripts/task_context.mjs` — adapted
- `scripts/collect_signed.mjs` — adapted
- `scripts/batch_driver/checkpoint_io.py` — byte-identical

## Mature logic actually reused

- `collector_guard.signed_response_projection` takes non-struck-through frontend `finalPrice`
  before the legacy `bestPromotion.purchasePrice`. `validate_main` enforces positive arrival
  price, logged-in response, exact requested SKU, detail identity and main-image evidence.
  Ordinary `price.p` is not silently treated as the arrival price.
- `collector_guard.ordered_variants` sorts the official dimension/button order, intersects
  actual SKU membership, and rejects missing frontend order, ambiguity, duplication and an
  incomplete matrix. It does not invent absent SKU combinations.
- `collector_guard.Checkpoint`, `checkpoint_status.pending_checkpoint_status`,
  `collection_policy.shouldRequest`, `partialRecheckEvidence`, `waitUntilNext`,
  `runner_lock.acquireRunnerLock` and `batch_driver/checkpoint_io.atomic_state` are reused.
  Valid price checkpoints survive restart; missing prices remain pending; rechecks are versioned
  and bounded. The Windows checkpoint replacement retry remains local, eight attempts maximum.
- `prepare_batch` retains original layouts, row/link evidence, source hash, keyword grouping,
  duplicate detection and row audits. Only the state destination changed.
- `package_live.live_data`, `plan_product`, `_detail_jobs`, `details`, `verify_table` and
  `finalize` are unchanged. Missing SKU prices prevent package generation. Existing user folders
  remain protected by the original collision/receipt rules. Product fields are first-row-only;
  all 22 columns, real frontend SKU order, JPEG encoding and MP4 structure checks remain upstream.
- `jpeg_cache.save_cached_jpeg` retains validated URL-keyed source bytes, coalesced downloads,
  atomic publication and repair from an existing valid cache.
- `verify_batch.run` independently recomputes rows from original per-SKU checkpoints and media
  expectations from source URLs. It checks workbook rows, URL-cache hashes, exact media sets,
  image encoding, video structure, keyword ownership and counts, rather than trusting receipts.
- `deliver_batch.verified_items`, `keyword_bins`, `write_manifest`, `write_zip`,
  `delivered_keys` and `incremental_items` retain VERIFIED-only delivery, whole-keyword splitting,
  incremental package comparison and ZIP CRC readback.
- `request_policy`, `browser_worker`, `native_page`, `runner_lock` and `variant_queue` are
  byte-identical. `collect_signed` retains the original per-product native response capture,
  actual page SDK/signing/XHR, source-product allowed SKU set, price snapshots, request clock,
  partial-price handling, budget/cooldown states, stop reasons and cleanup. It does not introduce
  a signature engine, browser engine, guessed business interface or alternate scrape route.

Tests pin the AST hashes of 23 original Python functions across the adapted modules, in addition
 to validating unadapted-file hashes. No upstream checkout or personal skills directory is needed
 to execute the tests or the migrated runtime.

## Thin adaptations only

1. `asset_paths`: resolve the explicit output root and task state under merchant home.
   Remove the process-global IPv4 `socket.getaddrinfo` monkey patch (transport/network policy
   belongs to the parent). The original material-host allowlist and `requests` material download
   function are unchanged; no price endpoint is added.
2. `prepare_batch` / `deliver_batch`: use the shared owned-state resolver, without changing
   parsing, business artifacts, delivery eligibility or ZIP logic.
3. `package_live` / `verify_batch`: offline `--help` before runtime imports. Rename the optional
   prior-receipts environment variable; no package, price or verification algorithm changes.
4. `variant_bridge`: externally supplied Python executable plus `-B`; no O2 discovery.
5. `collection_policy`: rename environment knobs, preserving original numeric defaults and bounds.
6. `task_context`: retain the original session/tab/probe/background validation, drop proprietary
   `wcli` path requirements, provide an explicit absolute-module browser loader and the shared
   owned-state resolver. The loader validates the Page/capture surface; it does not implement it.
7. `collect_signed`: load that external transport instead of proprietary main/preload/Page/daemon
   modules; use the owned state namespace; provide offline help. Arbitrary transport exception
   text is not persisted (only static error codes and known error classes), to avoid leaking
   credentials from an externally supplied adapter. No new business states or approval gates.

## Parent-supplied runtime contract

The parent is responsible for its existing cleaned environment, hash verification and launcher.
This migration does not add or change any of them. Launch entry files directly; standalone imports
resolve sibling migrated scripts, never a personal skills installation.

- `HEIDENG_MERCHANT_HOME`: required, parent-supplied independent merchant runtime home.
- `--root` (both `--root path` and `--root=path`) or `HEIDENG_COLLECTION_ROOT`: explicit business
  output directory. Final packages/delivery go there; runtime state does **not**.
- Default state: `HEIDENG_MERCHANT_HOME/mature/collection/batches/<sha256(canonical-output-root)>`.
  Python and Node resolve the same namespace; distinct roots get distinct batch state.
- `--state-dir` / `HEIDENG_COLLECTION_STATE_DIR`: explicit task state strictly below that
  merchant-owned `batches` namespace. Legacy `<root>/.collector_state` and `JD_COLLECTOR_*`
  environment variables are not implicitly reused. Explicit fresh batch subdirectories are
  supported; no automatic import of earlier personal skill state.
- `HEIDENG_COLLECTION_PYTHON`: optional parent-supplied executable for `variant_queue.py`
  (default `python`). Use the parent's isolated runtime, not a personal skill lookup.
- Optional pacing knobs retain original defaults:
  `HEIDENG_COLLECTION_MIN_INTERVAL_MS=30000`, `HEIDENG_COLLECTION_MAX_REQUEST_LIMIT=20`,
  `HEIDENG_COLLECTION_NAV_MIN_MS=60000`. Ordinary CLI request interval defaults to 30000 ms,
  maximum requests to 20. No platform-safety guarantee is implied by those defaults.
- `HEIDENG_COLLECTION_PRIOR_RECEIPTS`: optional explicit batch-owned receipt index, for the
  upstream same-product folder replacement mechanism. Omit unless parent provides that evidence.
- Original-price fallback remains the existing, explicit batch-local
  `--allow-original-price-fallback` flag. It is not enabled by this migration. It still requires
  the upstream batch-specific user authorization semantics; no new approval state is added.
- Dependencies are the original `requirements.txt`: openpyxl >=3.1, Pillow >=10.0, requests >=2.31.
  Node and Python are provided by the parent; no installation or authentication was attempted.

### Browser module boundary (conditional live route; not certified here)

`HEIDENG_COLLECTION_BROWSER_TRANSPORT` must name an **explicit absolute module file** exporting:

- `class Page`, with the original constructor `(session, idleTimeout, undefined, 'background')`;
- methods `setActivePage(tab)`, `startNetworkCapture(filter)`, `readNetworkCapture()`,
  `evaluate(expression)`, `newTab()`, `listTabs()` and `closeTab(tab)`;
- `sendCommandFull('navigate', {url, session, page, idleTimeout, windowMode:'background',
  surface:'browser'})` honoring the original native-navigation behavior.

The parent supplies a fresh task-local `browser_context.json` in the owned state directory:
`session` is an alphanumeric/hyphen/underscore string, `tab` is 32 uppercase hexadecimal
characters, `windowMode` is `background`, `idleTimeout` >=7200, and `probeSku` is the exact
8+-digit user-provided source SKU. There are no proprietary module paths in this contract.
Do not copy personal browser contexts or put cookies, tokens, device fields or signed URLs in it.

A conforming provider must prove all of the following before live collection can be described
as ready:

1. Capture starts before the native item navigation; completed business response bodies are
   available without destructive reads clearing pending capture entries.
2. Capture retains request/response identity, status, OPTIONS distinction, truncation indication
   and the page's transient native context needed by the unchanged `capturedBusiness` function.
   Context is immediately handed back to page memory and never logged or persisted.
3. `evaluate` executes in that actual native task page with its official SDK/XHR and does not
   fake response fields, compute substitute signatures, fetch guessed interfaces or export secrets.
4. `listTabs` exposes **only this task's owned tabs**. The upstream stale-tab cleanup closes item
   tabs returned by that list; a provider exposing a user's working tabs is not faithful/safe.
5. Refusal, verification, unknown completion, request clocks and task cleanup preserve the
   upstream stop/reconciliation semantics. A missing capture body or unsupported bridge cannot
   be replaced by scraping through a guessed route.

No such real provider was supplied or exercised in this task. The tests use only synthetic local
objects. A valid module shape and a cache-only zero-request run do not certify real transport
semantics or platform availability. Missing modules return static diagnostics; they are not
permission to install O2, discover a personal WebCLI installation, log in or bypass controls.

## Exact entrypoints

The provenance records the following original entry files. The parent `--entry` accepts
the four Python entries; MJS execution is separately blocked pending a reviewed browser transport.
The parent supplies `state/work/collection` as the source CWD; absolute entry files and sibling
imports do not depend on the repository being the CWD. Tests run actual preparation/delivery
and cache-only collection from that owned work-directory layout.

The parent provenance entrypoints are:

- `scripts/prepare_batch.py` — offline explicit-source input preparation;
- `scripts/collect_signed.mjs` — preserved bounded per-product native route; conditional transport;
- `scripts/package_live.py` — complete per-SKU evidence packaging;
- `scripts/verify_batch.py` — independent package/evidence verification;
- `scripts/deliver_batch.py` — VERIFIED-only workbook/CRC ZIP delivery.

All five accept runnable `--help` without a runtime home, browser, login or state creation.
Python launch form: `<parent-python> -B -X utf8 <absolute-entry-file> <arguments>`.
Node launch form: `<parent-node> <absolute-entry-file> <arguments>`.
For offline packaging, provide preexisting trusted checkpoints and valid media caches; cache misses
can invoke the original explicit public-material downloader. No such download was performed here.

## Precisely blocked / excluded upstream executable paths

These are not replaced or declared usable by the parent merchant runtime:

| Upstream script(s) | Reason / exact missing surface |
| --- | --- |
| `scripts/collect_signed.mjs` (migrated but live-unverified) | A real task-scoped Page/capture/navigation/evaluation provider with the semantics above has not been supplied or certified. Preserving the source and passing synthetic tests is not full collection readiness. |
| `scripts/click_collector.mjs` | Its own `wcli.main/preload/page` and `daemon-client.js` bootstrapping, plus click-observation/DOM surface, is not migrated. No click engine is recreated and no fallback is launched. |
| `scripts/click_probe.mjs`, `scripts/clean_session_click_test.mjs` | Standalone proprietary browser/session/click diagnostics are outside the selected transport route; no merchant-native click bridge is verified. |
| `scripts/diagnose_native.mjs`, `scripts/interface_probe.mjs`, `scripts/verify_interface.mjs`, `scripts/recovery_probe.mjs` | Each still imports the upstream saved `wcli` preload/Page module or diagnostic tab context. These probe/recovery entrypoints are not copied, and cannot be used to bypass missing capture semantics or relaunch unknown requests. |
| `scripts/click_supervisor.py` | Drives the excluded click/recovery chain. Migrating it without that native surface would misrepresent readiness. |
| `scripts/supervisor.py` | Calls the excluded `recovery_probe.mjs`; the migration exposes bounded original entrypoints, not a new supervisor with guessed recovery. |
| `scripts/self_check.py` | Searches the personal `.o2/npm/node_modules/@jd/webcli` installation and a personal Desktop output directory, and recommends O2 installation. The parent owns runtime/dependency checks instead. |
| `scripts/batch_driver/batch_driver.py`, `start_new_batch.py`, `driver_keeper.py`, `resume_after_*.py`, `monitor_batch.ps1` | The long-running orchestration family depends on its own `JD_BATCH_*`, saved driver/session state and full staging/fallback/recovery executable chain. That chain is deliberately not migrated or reconstructed; only the mature local `checkpoint_io.py` primitive is selected. |
| `scripts/batch_driver/stage_pending_materials.py`, `stage_cached_assets.py`, `staging_cache.py`, `package_with_artifacts.py`, `package_with_fallback.py`, `verify_batch_fallback.py`, `original_price_fallback.py`, `prior_receipts.py`, `workbook_author_openpyxl.py` | Supplementary full-driver staging/artifact/fallback chain is not required by the bounded five-entrypoint package. Main mature packaging/verification/workbook logic is already copied. The modified unpublished `stage_pending_materials.py` is specifically excluded. |

No full-chain supervisor, click fallback, new task states, readiness labels or authorization gates
are invented to hide those limitations.

## Offline verification ledger

1. Before migration: wrote `tests/test_mature_collection.py`, ran
   `python -X utf8 -B -m unittest tests.test_mature_collection -v`, and observed 15 expected FAILs:
   `tracked mature collector not migrated`. No collection production files existed yet.
2. Copied pinned tracked blobs and applied the thin boundary changes. First green pass: 15/15.
   One test initially called the original delivery function with the wrong signature; the test
   was corrected to call `verified_items(report, stage, root)`, not the upstream function.
3. Expanded original-function and real-entry verification: 19/19 targeted tests pass. Includes
   23 pinned original-function AST hashes, source identity and price preference, real two-dimensional
   SKU intersections/order, missing-price non-packaging, successful checkpoint reuse, bounded
   checkpoint replacement, independent price recomputation despite mutated metadata, valid-JPEG
   source-hash mismatch rejection, 22-column workbook readback, actual preparation/delivery CLI,
   CRC ZIP readback, VERIFIED-only delivery and Python/Node owned-state parity.
4. The actual mature collection driver executes an all-success-cache round with a synthetic
   supplied transport: zero price requests, zero navigations, unchanged evidence and released lock.
   No live browser is opened. The other Node tests exercise the original projection, capture
   classification and bounded recheck scheduling functions.
5. Re-read all 28 selected blobs from pinned Git and compared both hashes and `adapted` flags;
   19 files are byte-identical. This check detects unpublished upstream working-tree contamination.
6. Started the repository's complete offline suite through `python -X utf8 -B tests/run_offline.py`
   (fresh HOME, blocked socket network). Parent/runtime files changed concurrently during execution;
   those runs are not a frozen integration acceptance result. Several non-collection tests reported
   errors, while a representative failure-repair test passed when rerun alone in a clean environment.
   The parent explicitly owns final frozen-suite validation once all workers finish.
7. Before handoff, rerun the 19 targeted tests and audit all raw source/final hashes after the last edit.
   No collection file is edited after the final finished report.

### Decisions / limitations

- Keep the original mature Python script entrypoint/import layout instead of adding another
  collection implementation or parent integration layer. Cost if the parent requires a different
  launcher API: adjust only that external boundary, not collection rules.
- Put all runtime state in the merchant-home namespace, but leave explicit final business artifacts
  in the chosen output root. Cost if a caller relied on legacy state: it must explicitly provide
  owned migrated evidence; personal state is never discovered/imported implicitly.
- Preserve the exact original SDK/native capture implementation while conditioning live use on an
  external provider; do not claim full collection readiness. The provider remains the blocker.
- Scope restrictions and source READ ONLY take precedence over general skill-maintenance or
  commit/push advice. No personal skill or upstream Git repository is modified or synchronized.
