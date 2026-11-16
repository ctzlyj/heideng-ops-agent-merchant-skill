# Bounded mature listing reuse — 2026-11-16

## Approved boundary / execution ledger

- Source: `ctzlyj/jingmai-hot-product-mover-skill`, MIT, v1.2.6,
  commit `3ee08af2f3970f88d39756f1906040efe75117dc`. Source checkout read-only.
- Destination: `mature/listing/**`, `tests/test_mature_listing.py`, this document only.
- No parent CLI, registry, distribution or image changes; no new runtime or plan gate.
- Preserve mature builders, image/detail/SKU grouping, explicit store/profile checks,
  generation receipts, review digests, publish/reconcile semantics.
- Only parent `heideng_merchant.mature_image` supplies merchant image edits.
  No company credentials, registry lookup, personal skill search or alternate providers.
- Isolated dependency discovery: siblings below `<package>/mature` only.
- No live auth, generation, merchant writes, commit/push.

Plan: (1) behavior tests and observed RED; (2) Git-tracked bounded copy;
(3) provider/path/video boundaries only; (4) GREEN + offline import/help;
(5) provenance hashes and final scope/source immutability check.

Ruling: no subagent tools are exposed in this session; execute inline and run
independent read-only inspections in parallel. Do not create user-owned chats.

Ruling: do not copy upstream config or producer. Runtime config/reference snapshots
and output defaults belong to merchant state, never the shipped source directory.
The legacy 11190 verification/production path is blocked until an external video
handoff protocol exists; existing upload/binding primitives remain documented.

## Bundled surface (not a replacement business engine)

Package root: `C:\Users\caotong.888\.codex\worktrees\merchant-mature-reuse\黑灯运营智能体商家版`.
Bundle: `<package>/mature/listing`. Every selected runtime/resource file is
enumerated in `provenance.json.files`; only those paths are intended for distribution.
The provenance object itself is excluded from that map. Raw Git blob hashes are
`upstreamSha256`; final raw file hashes are `sha256`. No hash-time EOL normalization.
`adapted` is exactly whether the two byte hashes differ. MIT LICENSE is unmodified.

### Python command entrypoints (all relative to mature/listing)

| Entrypoint | Actual callable purpose | Required inputs / limits |
| --- | --- | --- |
| scripts/jdo_listing_mvp.py | live category reference; local preflight/build-payload; image upload; create/full-edit/shared-image PATCH; official readback | Explicit store Profile/config for live operations; source schema/reference and confirmed facts. Existing write identity guards retained. |
| scripts/jd_product_mover.py | collect/materialize/build listing/audit workbook from source data | Merchant-supplied category rules/reference; browser-video fallback is explicitly unavailable if its dependency is missing. |
| scripts/jd_product_pipeline.py | original local-listing/upload/prevalidate/create/verify pipeline | Merchant store/business config and rules/reference; source-video automation is blocked. |
| scripts/photo_listing.py | init/reference/facts/questions/plan/generate/review/accept/prepare/publish/verify/reconcile; sale-template discovery/application | CLI init --shop needs the optional connector. Python create_package() accepts an explicit verified store; verify_store() no longer requires connector/auth helper and directly retains active-POP/name/vendor/profile checks. |
| scripts/company_jpeg_edits.py | original confirmed-prompt JPEG plan; dry-run or generation receipt | --plan, --output; only gpt-image-2.5. No provider fallback. |
| scripts/image_patch_update.py | image-only PATCH preserving live color buckets and SKU prices, then readback | --profile, --store-config, --product-ids, --url-map, --confirm PATCH_PRODUCT_IMAGES; bodies-dir optional, defaults to merchant state. |
| scripts/detail_repair.py | original detail plan/generate/review/apply/reconcile workflow | Existing published photo package; original review/readback guards retained. |
| scripts/merchant_template_import.py | workbook-to-local listing drafts | --input, --output-root; merchant-supplied rules/reference. |
| scripts/matrix_listing.py | snapshot/generate/upload/build/validate/publish/verify/patch-fix | Original source apply-detail and variants; one merchant image model; STARTED/UNKNOWN/legacy failed generation is not replayed, including --redo. |
| scripts/set_product_brand.py | original multi-SKU full-edit brand converter and preservation readback | Explicit profile/shop/brand; preserves SkuUUid/SkuId/color mapping; deliberately omits SkuStockNum. Lost submit response is never automatically retried. |
| scripts/publish_local_draft.py | original reviewed local draft publication and propagation verification | Explicit profile/store/rules/reference, original confirmation and existing-product detection. |
| scripts/photo_video.py | --diagnose legacy manifest; original upload/save/SKU-bind receipt implementation is retained | Actual bind remains blocked before platform access by the missing external-video handoff protocol. |
| scripts/jdo_large_body_bridge.py | internal official-CLI large-body bridge, not a business command | --runtime, --request; original Python 3.12 embedded-runtime interface probe retained. |

Supporting unchanged business libraries include `detail_pages.py`,
`photo_contract.py`, `sale_attr_templates.py`, `image_quality_gate.py`,
`hot_replica_mode.py`, `source_pricing.py`, `component_rounded_pricing.py`,
and `deferred_publish_batch.py`. No bootstrap, installer, original configs,
source credentials, user output packages, original tests, or private producer are copied.

### Exact Python functions usable independently

- `jdo_listing_mvp.build_publish_schema(manifest)`,
  `write_publish_payloads(input_path, output_dir)`,
  `validate_manifest(path, manifest, reference)`,
  `build_shared_image_update_payload(manifest, detail, product_id)`,
  `shared_image_audit(manifest, detail)`.
- `photo_listing.create_package(root, store, photos, title, ...)`,
  `build_listing(manifest, root, reference)`, `verify_store(store)`,
  `prepare_package`, `publish_package`, `reconcile_package`, `verify_package`;
  `photo_contract.review_digest` / `can_submit` retain original change/replay checks.
- `detail_pages.build_detail_plan`, `check_detail_set`,
  `wareeditor_component`, `build_detail_patch_body`, `readback_detail`;
  `detail_repair.plan/generate/review/apply/reconcile`.
- `image_patch_update.build_image_patch_payload(detail, url_map)`,
  `verify_patch(before, after, mapping)`, `patch_product(...)`.
- `set_product_brand.build_edit_schema(apply, brand_id)`,
  `build_edit_body(apply, brand_id)`, `verify_preservation(before, after, brand_id)`.
- `photo_generation.generate_tasks(tasks, out, client=None, redo=None)` and
  `company_jpeg_edits.generate_plan(plan, run, client=None)`: mature per-image receipts,
  cache hashes and unknown-result reconciliation, not the old image_generation plan gate.

### Image boundary

Only the legacy `CompanyPhotoClient` / `CompanyClient` transport boundaries and
model lists target the parent `heideng_merchant.mature_image`. The actual parent
interface accepts local Path image references and returns JPEG bytes. The parent owns
SUFY transport, API-key reading, exact endpoint/model and zero transport retries.
Original four-slot concurrency and one-start-per-second client pacing are retained.
No company-model catalog, key fallback, Windows registry or personal Skill search remains.
The primary provider is LTS4AI; retained ledger `externalAllowed:false` means no alternate
provider fallback, not a claim that the primary transport is an internal company service.

### State and immutable sources

Mutable defaults live at
`HEIDENG_MERCHANT_HOME/mature/listing`, falling back to
`~/.heideng-merchant/mature/listing`. This includes reference/store/rules defaults,
image-upload/PATCH bodies, migrations, bridge extraction/probe cache, and brand-run output.
Explicit package/run/output parameters remain original user-controlled inputs.
No default writes to `mature/listing` or the upstream checkout. Import and --help create no state.
Parent child launch supplies JDO_HOME and JDO_CLI_HOME under
`state/cli-home/.jdo-cli`, a private `state/work/listing` CWD, and the reviewed official
executable via JDO_CLI_PATH. No parent CLI/distribution/registry/image files are edited here.

## Exact video primitives versus unavailable producer

Independently reusable in `jd_product_pipeline.py`:
`video_upload_url_params(video_path, file_size, jd_video_id=None)`,
`build_video_binding_body(product_id=..., sku_id=..., video=..., tag=...)`,
`video_zone_id()`, `query_video(zone_id, video_id)`,
`query_video_relations(zone_id, video_id)`, `existing_video_materials(sku_ids)`,
`video_is_ready(status)` and `video_relation_audit(relations, sku_ids, video_id)`.
These builders/readers do not generate a video or establish a producer handoff.

The retained `photo_video.bind_video(manifest_path, mp4=None, confirm=..., ...)`
contains the actual mature checkpointed implementation: obtain upload URL, transfer
`video_file`, save zoneVideoDTO, wait for transcode/review, bind each SKU through
sku-materials/batch, then query and audit relations. Upload/save/bind uncertainty
is checkpointed before any attempt and is not re-POSTed. However its entry guard
`video_handoff.check_handoff` now reports missing external-video protocol and stops
before probing, credentials, transfer, save or binding. `find_video_skill` returns None
without personal-root/env/catalog lookup; no 11190 subprocess is run.
`automate_main_video` likewise blocks when given a source video.

Legacy 11190 verification expected manifest-local source paths and SHA256/cover SHA,
producer run/mode/label/task identity, bindable/QC attestations, duration, and the
original-byte-bound voice review. An externally owned producer protocol and attestation
verification have NOT been designed or substituted here. Do not fabricate those fields,
rewrite a source SHA to pass a gate, or call diagnose() readiness a bind authorization.
The parent's current video-binding route points at jdo_listing_mvp.py (which has no
video-binding CLI command); mapping a real binder is parent integration work, not part
of this bounded edit.

## Precise blockers / non-claims

1. Live authorized official jdo-cli and explicit non-default store Profile/config are
   required. This task installs/connects/authenticates nothing. Existing matching
   profile/venderId/shop identity must pass the retained readback/write guards.
2. Optional `<package>/mature/jingmai-cli-linker/scripts/linker.py` is absent/pending
   distribution permission. Missing file is explicit; no connector is reimplemented,
   installed, fetched, or borrowed from personal roots. Parent `connection` alias
   routing, if desired, needs its own reviewed integration.
3. Merchant rules, store/business config and current category/reference snapshots are
   intentionally NOT distributed. Provide them or run the authorized original
   refresh-reference command; absence is not filled with invented/default shop data.
4. The optional `browser_source_read` source-video fallback is NOT bundled. Its call
   sites report the missing dependency; no internal browser/O2 transport is substituted.
5. `heideng_merchant.mature_image` and a process-only
   HEIDENG_MERCHANT_LTS4AI_API_KEY are required for paid images. Actual parent-interface
   compatibility is tested offline with a local core fixture, NOT by paid generation.
6. No text, alternate image, or video provider is available. External video producer /
   upload handoff protocol is explicitly blocked as detailed above. No private producer copied.
7. Large official requests still need the unchanged PyInstaller reader / probed original
   jdo-cli embedded runtime and a compatible Python 3.12. No bridge/CLI installation,
   authorization or large live request was performed.
8. Category/activity/platform constraints and live image/detail/SKU review outcomes
   cannot be inferred from offline tests. These are callable mature implementations,
   not a claim of merchant live readiness or generic support for every category field.

## Verification / TDD evidence

- Initial RED before copy: 15 tests could not load the absent mature bundle.
- RED on actual audited upstream behavior: personal dependency discovery, old key lookup,
  mandatory connector, old multi-model client, and producer lookup conflicted with the
  approved boundary. Profile/write-drift and business-preservation tests characterize
  the reused upstream safety, rather than a new implementation.
- Additional observed RED: matrix timeout was submitted again on rerun; default PATCH
  had no body file or verified store; full-edit timeout was retried four times. Narrow
  fixes reuse existing ledgers/store verifier and eliminate unknown transport replay.
- Parent-interface RED identified Path reference semantics; the real parent boundary
  is now covered through a local-only SUFY core fixture (never a live model request).
- Windows help subprocess capture explicitly decodes UTF-8; no inherited credential
  environment or personal HOME is used for import/help validation.
- Final command/results and hashes are recorded below once frozen.

Only this document and the allowed new test/bundle files are authored in this task.
Concurrent parent/sibling edits elsewhere in the worktree are intentionally preserved.
No upstream/personal Skill edits or sync are attempted: scope and no-commit/no-push
instructions override general capability-maintenance defaults.

- Additional RED/GREEN: optional-linker photo verification directly rejects inactive/non-POP stores before marking a profile verified, retaining the original official-verifier checks.

- Original CompanyClient four-slot limiter and one-start-per-second pacing retained around the parent transport; local-clock pacing regression observed RED then GREEN.

### Frozen result (this task)

- Sanitized Python `-I -B` runner: fresh HOME/USERPROFILE/merchant namespace,
  credential env excluded, socket connections forbidden; **24 tests passed**
  in **10.840 seconds**, exit **0**. This includes importing all **26** selected
  Python modules and `--help` on all **13** registered entrypoints from an empty
  working directory without writing state.
- Reusable command (from package root):
  `python -B -m unittest discover -s tests -p test_mature_listing.py -v`.
  The stricter sanitized subprocess was also executed for the recorded result above;
  parent may use its existing offline harness after all sibling tasks freeze.
- **35/35** final file SHA256 values match final raw bytes: **16 adapted**, **19 exact
  original Git blobs**. LICENSE unchanged. Only these files plus provenance.json
  exist in the listing subtree (36 files total; no bytecode/config/output/user assets).
- Upstream still resolves to the audited Git repository, HEAD
  `3ee08af2f3970f88d39756f1906040efe75117dc`, with a **clean Git status**.
  Each original hash was independently recomputed from `git show HEAD:path`.
- Parent `source_path` final raw-hash validation passed for listing, photo-listing,
  matrix-listing, images and the current video-binding mapping. A mapping/hash pass
  does NOT mean video binding is available; the protocol/mapping blockers remain.
- Forbidden company-provider/key/registry/personal-root/catalog/old-image-gate scan:
  clean across selected runtime scripts/references. Scoped whitespace check passed.
- Frozen provenance.json SHA256:
  `b0d1cac4eb351be9e8ccf2d4b8689a02fc54334572a54335588d33d3593d8ac3`.
- No auth/model/merchant write, private producer, commit, push, parent file edit or
  original-checkout write was performed. Other workers' edits are not part of this task.

Read-only video diagnostic command (not bind authorization):
`python photo_video.py --manifest <listing-package>/manifest.json --confirm DIAGNOSE --diagnose`.


## Parent additional source-path restoration / 2026-11-16

- Added actual pinned `taobao_product_mvp.py`, `hot_replica_apply.py`, `hot_replica_price_plan.py`, `hot_replica_preflight.py`, rather than relabeling the JD-only pipeline as Taobao/Tmall support.
- Taobao/Tmall identifier parsing is unchanged; only default mutable config paths move under merchant state. Original replica apply/price logic remains. The price CLI's literal percent help formatting was corrected after an observed failure.
- The original preflight's private saved-Key lookup and implicit Gemini request are removed. Its parsing/sheet/brand logic is retained, while `ask` refuses an unconfigured external vision provider before image I/O or HTTP. This is an explicit incomplete boundary, not a completed vision replacement.
- Complete hot-replica publish/continuity orchestration is not yet migrated. The generic legacy pipeline's unknown-publish retry path still needs the existing mature receipt guard before a merchant-write readiness claim. No real publish was executed; do not infer support from builders/help.
- Parent corrected video dispatch to the real `photo_video.py` diagnostic/binder. External producer handoff remains unconfigured; no successful binding is asserted.
- The additional three tests observed RED then GREEN for missing entries, real identifier parsing, early unconfigured-vision refusal, and each original command's help.


## 原发布防重复规则的跨入口衔接
通用 jd_product_pipeline 原来会在重进时先把 SUBMITTING 覆盖为 RECEIVED/FAILED，导致丢失未知提交状态。本轮实际复现后直接复用原 matrix_listing.publish_guard：重进前检查原状态、发品前沿用原 SUBMITTING+payloadSha256，并在异常/没有productId时保留原SUBMITTING，不自动重发。
没有新增发布审批/证明/恢复状态机。已跑原guard调用和原状态文件不被覆盖的回归；未提交真实商品。
全量复刻其他入口和低层独立发布命令仍需按同一成熟规则继续核对，不以这处修复代替全部流程完成。
