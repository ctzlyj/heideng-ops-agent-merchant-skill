# Native SKU material maintenance implementation plan

> Implementation uses executing-plans + TDD in this existing dedicated merchant checkout. The user has delegated remaining design and implementation; no further design gate or real-shop authorization is inferred.

**Goal:** Native same-shop SKU material census, gap reporting, and explicitly approved, durable missing-slot binding, using already uploaded originals or host-reviewed text. No generators.

**Architecture:** A focused `sku_material_contract.py` owns fixed protocol names, strict read normalization, receipt-bound sources and mandatory generic-operation guards. `sku_materials.py` owns product census, bounded 50-SKU reads, deterministic batch plans, single-range approval and serial execution/readback. Reuse Operations' fingerprint, deadline, transport/stdin and unknown locks; no parallel writers.

**Tech:** Existing Python stdlib, merchant state locks, current official CLI transport. No installed business package imported/executed/copied.

## Evidence and limitations
- Current official anonymously readable API830 catalogue names GET sku-materials and POST sku-materials/batch, plus health-infos as 商品信息健康分. API card is authenticated and must not be queried on development's real profiles.
- Read-only installed POP reference documents `skuIds`, `materialTypes`, `scopeSet` (1 images/2 text); materials array; 31/32/33/36 image types; 1002 text; positive order; imageMaterial imgType=1/replaceType=1/skuImages index=1 imgUrl=jfs path; textMaterial.contents.
- This is a reference-evidenced adapter, NOT a live-category/shop verified protocol. Production transport must still validate the current authenticated capability schema before dispatch. Unknown read structures refuse instead of guessing.
- healthScore and improvementList are native information-health evidence; portal commodity-score equivalence is unverified. Missing score is never zero. On-sale scope is independently checked, not inferred from a score row.
- Maintenance initially fills **absent** slots only. Existing empty/approved/pending/rejected slots are not automatically overwritten. Repair, appeal, short-title import, video binding and visual review remain separate.
- All supported material types and orders for targeted SKUs are read before and after; exact queried preservation is checked. This is not a transaction snapshot or proof of preservation for unqueried future material types.
- Original API acknowledgement is not per-SKU submission count; full target readback is not audit approval or score recalculation. Unknown requests remain unknown even if targets match.

## Global constraints
- Only synthetic tests/shops; no real OAuth, writes, paid calls, employee credentials or internal gateway.
- Internal checkout, installed Skills and video upstream remain read-only.
- No arbitrary image URLs: reference a known same-shop original upload task with fresh exact imgId/imgUrl readback and host content-review approval. No inference from matching filename or desired target.
- Runtime/official source changes, incorrect profile, malformed IDs, omitted/duplicate/foreign SKU rows, material drift and final TTL expiry must stop before POST.

## Tasks
- [x] 1. Tests RED: complete/reordered native census, missing/foreign/duplicate response, original uploads, absent-only changes, generic bypass, no approval, timeout/partial response, preservation drift, batch resume, wrong shop, TTL.
- [x] 2. Implement strict material contract and read-only audit. Preserve full supported query scope; honest completeness and information-health terminology.
- [x] 3. Integrate mandatory Operations prepare/execute/readback guard and deterministic batch service. One scope approval, per-chunk ledger, never replay unknown or already started tasks.
- [x] 4. CLI/Skill/registry instructions; user-facing natural language examples and evidence limitations.
- [x] 5. Isolated full suite, fresh-HOME installed 1000-SKU smoke and previous regressions, archive audit, private push and actual GitHub-clone roundtrip. Record hashes and failures honestly.

## Review focus
- Upload response modified/rehashed: full original image-byte evidence plus exact ID/url readback.
- Pending/rejected/empty existing slots: report only, no silent overwrite.
- Every preserved order/type is checked; reordered response accepted, lost last SKU or extra unexpected slot rejected.
- Repeated plan after accepted/unknown chunk: same durable plan/tasks, not fresh writes.
- A target match after timeout never unlocks writes; per-chunk acknowledgement, content verification, audit status and score remain independent.

## Verified implementation additions
- Full parent-plan canonical changes and ordered membership are checked at approve/execute; one durable parent approval and final deadline cannot be replaced or extended by task approval.
- Separate first upload acknowledgement and any original resolved readback anchor image source; contradictory rehashed receipts refuse. Legacy uploads lacking independent evidence refuse rather than guess.
- Official cmd_info primary source proves the exact open-metadata GET route. Actual card method/path/schema is queried and fingerprinted; only the tested limited JSON Schema shape is accepted. No real merchant card queried.
- Three independent findings reproduced RED (four tests), fixed and narrowly rechecked; source gate separately tested.
- Local verification: 352 isolated tests, eight fresh-install/source-boundary smokes, archive audit. Actual GitHub roundtrip remains to record after private push.

## Actual GitHub follow-through
Completed actual GitHub clone of code commit 43dfb9962f369595ac7b0f2d45dba322e6328eee, fresh venv/public dependency, identical archive SHA 812ed0eff49f9489235adbedddd8a13ec09fa4911380c47f0e60646f664b5144, fresh HOME installation/onboarding, 352 isolated tests and all eight smokes. Detached source remains clean. Full objective remains active; no real merchant authorization/writes/model spend or formal release.
